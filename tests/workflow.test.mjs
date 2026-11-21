// Runs the workflow's own Code nodes (read from the n8n JSON) against canned DNS answers.
// No network: every DNS reply below is a fixture, including the real parked-domain trap.
import { readFileSync } from "node:fs";
import assert from "node:assert/strict";

const wf = JSON.parse(readFileSync(process.argv[2] || "workflows/sender-domain-health.n8n.json", "utf8"));
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
const node = (prefix, ...args) => new AsyncFunction(...args, wf.nodes.find((n) => n.name.startsWith(prefix)).parameters.jsCode);
const lookupsFn = node("DNS Lookups", "$json");
const rulesFn = node("Rules:", "$json");
const compareFn = node("Compare With Last Run", "$input", "$getWorkflowStaticData");
const reportFn = node("Build Digest and Alert", "$input");

// ---- a fake public DNS: "name TYPE" -> answers; "FAIL" simulates a resolver error ----
const DNS = {
  // a clean, enforced setup
  "good.example TXT": ["v=spf1 include:_spf.google.com -all"],
  "_spf.google.com TXT": ["v=spf1 include:_netblocks.google.com ~all"],
  "_netblocks.google.com TXT": ["v=spf1 ip4:35.190.247.0/24 ~all"],
  "_dmarc.good.example TXT": ["v=DMARC1; p=reject; rua=mailto:dmarc@good.example"],
  "good.example MX": ["1 aspmx.l.google.com."],
  "k1._domainkey.good.example TXT": ["v=DKIM1; k=rsa; p=MIIBIjANBg"],
  // monitoring mode with no report address, the state of the author's own domain
  "watch.example TXT": ["v=spf1 include:_spf.mx.cloudflare.net ~all"],
  "_spf.mx.cloudflare.net TXT": ["v=spf1 ip4:104.30.0.0/19 ~all"],
  "_dmarc.watch.example TXT": ["v=DMARC1; p=none;"],
  "watch.example MX": ["58 route2.mx.cloudflare.net."],
  // a subdomain run by an email tool: no SPF or MX at the name, DMARC inherited
  "send.watch.example TXT": [],
  "_dmarc.send.watch.example TXT": [],
  "send.watch.example MX": [],
  "s1._domainkey.send.watch.example TXT": ["k=rsa; t=s; p=MIIBIjANBg"],
  "s9._domainkey.send.watch.example TXT": [],
  "old._domainkey.send.watch.example TXT": ["v=DKIM1; p="],
  // a deep subdomain: the policy comes from the closest parent that has one, never from the bare ending
  "a.b.deep.example TXT": [],
  "_dmarc.a.b.deep.example TXT": [],
  "_dmarc.b.deep.example TXT": [],
  "_dmarc.deep.example TXT": ["v=DMARC1; p=reject; sp=quarantine"],
  "a.b.deep.example MX": [],
  "x.none.example TXT": [],
  "_dmarc.x.none.example TXT": [],
  "_dmarc.none.example TXT": [],
  "x.none.example MX": ["10 mx.none.example."],
  // the parked-domain trap: a wildcard answers every TXT question, _dmarc included
  "parked.example TXT": ["v=spf1 -all"],
  "_dmarc.parked.example TXT": ["v=spf1 -all"],
  "parked.example MX": ["0 ."],
  // too many tools: the same include reached twice counts twice, a macro cannot be followed
  "heavy.example TXT": ["v=spf1 include:a.example include:b.example include:a2.example include:c.example a mx exists:%{i}.x.example ?all"],
  "a.example TXT": ["v=spf1 include:a2.example ~all"],
  "a2.example TXT": ["v=spf1 include:a3.example ~all"],
  "a3.example TXT": ["v=spf1 ip4:192.0.2.1 ~all"],
  "b.example TXT": ["v=spf1 include:b2.example include:b3.example ~all"],
  "b2.example TXT": ["v=spf1 ip4:192.0.2.2 ~all"],
  "b3.example TXT": ["v=spf1 ip4:192.0.2.3 ~all"],
  "c.example TXT": "FAIL",
  "_dmarc.heavy.example TXT": ["v=DMARC1; p=quarantine; sp=none; pct=50; rua=mailto:d@heavy.example"],
  "heavy.example MX": ["10 heavy-example.mail.protection.outlook.com."],
  // broken records
  "broken.example TXT": ['"v=spf1 ip4:192.0.2.9 " "+all"', "v=spf1 -all"],
  "_dmarc.broken.example TXT": [],
  "broken.example MX": ["10 mx.broken.example."],
  "open.example TXT": ["v=spf1 ip4:192.0.2.9 +all"],
  "_dmarc.open.example TXT": ["v=DMARC1; p=reject", "v=DMARC1; p=none"],
  "open.example MX": ["10 mx.open.example."],
  // the resolver itself fails
  "down.example TXT": "FAIL",
  "_dmarc.down.example TXT": ["v=DMARC1; p=reject"],
  "down.example MX": ["10 mx.down.example."],
};
const helpers = {
  httpRequest: async ({ url }) => {
    const u = new URL(url);
    const key = u.searchParams.get("name") + " " + u.searchParams.get("type");
    assert.ok(key in DNS, "unexpected DNS question: " + key);
    if (DNS[key] === "FAIL") return { Status: 2 };
    const type = u.searchParams.get("type") === "MX" ? 15 : 16;
    return { Status: DNS[key].length ? 0 : 3, Answer: DNS[key].map((data) => ({ type, data })) };
  },
};
const check = async (domain, dkim_selectors = []) => {
  const raw = (await lookupsFn.call({ helpers }, { domain, dkim_selectors })).json;
  return { raw, v: (await rulesFn.call({}, raw)).json };
};
const codes = (v, level) => v.findings.filter((f) => !level || f.level === level).map((f) => f.code);

// ---- lookups + rules ----
let { raw, v } = await check("good.example", ["k1"]);
assert.equal(raw.spf_lookups, 2);
assert.deepEqual([v.status, v.dmarc_stage, v.mailbox_provider, v.senders], ["PASS", "reject", "Google Workspace", ["Google Workspace"]]);
assert.deepEqual(v.findings, []);

({ v } = await check("watch.example"));
assert.deepEqual([v.status, v.dmarc_stage], ["WARN", "monitoring"]);
assert.deepEqual(codes(v, "warning"), ["dmarc_monitoring_only", "dmarc_no_reports"]);

({ raw, v } = await check("send.watch.example", ["s1", "s9", "old"]));
assert.equal(raw.dmarc_inherited, true);
assert.equal(raw.dmarc_name, "_dmarc.watch.example");
assert.deepEqual(codes(v, "blocker"), ["dkim_selector_missing", "dkim_key_revoked"]);
assert.ok(codes(v).includes("spf_not_at_this_name") && codes(v).includes("mx_missing") && codes(v).includes("dmarc_inherited"));

({ raw, v } = await check("a.b.deep.example"));
assert.deepEqual([raw.dmarc_inherited, raw.dmarc_name, v.dmarc_stage], [true, "_dmarc.deep.example", "quarantine"]); // sp= applies to subdomains

({ raw, v } = await check("x.none.example")); // the fake DNS throws if "_dmarc.example" were asked
assert.equal(raw.dmarc_inherited, false);
assert.deepEqual(codes(v, "blocker"), ["spf_missing", "dmarc_missing"]);

({ v } = await check("parked.example"));
assert.deepEqual([v.status, v.dmarc_stage], ["FAIL", "invalid"]);
assert.deepEqual(codes(v, "blocker"), ["dmarc_not_a_policy"]);

({ raw, v } = await check("heavy.example"));
// own record: 4 includes + a + mx + exists = 7; a.example -> a2 -> a3 = 2; b.example = 2; a2.example again -> a3 = 1
assert.equal(raw.spf_lookups, 12);
assert.equal(raw.spf_lookups_exact, false); // c.example could not be read
assert.deepEqual(raw.lookup_errors, []); // a broken include is not a failed check
assert.deepEqual(codes(v, "blocker"), ["spf_too_many_lookups"]);
assert.deepEqual(codes(v, "warning"), ["spf_neutral", "dmarc_subdomains_open"]);
assert.ok(codes(v, "note").includes("dmarc_partial") && codes(v, "note").includes("spf_count_is_minimum"));
assert.equal(v.mailbox_provider, "Microsoft 365");

({ v } = await check("broken.example"));
assert.deepEqual(codes(v, "blocker"), ["spf_multiple", "dmarc_missing"]);

({ v } = await check("open.example"));
assert.deepEqual(codes(v, "blocker"), ["spf_allows_everyone", "dmarc_multiple"]);

({ raw, v } = await check("down.example"));
assert.equal(raw.lookup_errors.length, 1);
assert.deepEqual([v.status, v.dmarc_stage, codes(v)], ["ERROR", "unknown", ["lookup_failed"]]); // never reported as "missing"

// ---- compare with last run + report ----
const memory = {};
const run = async (verdicts) => {
  const compared = await compareFn({ all: () => verdicts.map((json) => ({ json })) }, () => memory);
  const report = (await reportFn({ all: () => compared }))[0].json;
  return { changes: compared.map((c) => c.json.change), report };
};
const verdict = (domain, status, findingCodes = [], spf = "v=spf1 -all") => ({
  domain, label: "", status, dmarc_stage: "reject", spf, dmarc: "v=DMARC1; p=reject", spf_lookups: 1,
  findings: findingCodes.map((code) => ({ code, level: status === "FAIL" ? "blocker" : "warning", issue: code + " issue", plain: "plain", fix: "fix" })),
});

let r = await run([verdict("a.example", "PASS"), verdict("b.example", "FAIL", ["dmarc_missing"])]);
assert.deepEqual(r.changes, ["new", "new"]);
assert.equal(r.report.needs_alert, true); // a first check that already fails
assert.ok(r.report.alert.includes("b.example") && !r.report.alert.includes("a.example"));
assert.ok(r.report.digest.includes("1 failing, 0 with warnings, 1 passing"));

r = await run([verdict("a.example", "PASS"), verdict("b.example", "FAIL", ["dmarc_missing"])]);
assert.deepEqual(r.changes, ["same", "same"]);
assert.deepEqual([r.report.needs_alert, r.report.alert], [false, ""]); // nothing new: no alert

r = await run([verdict("a.example", "WARN", ["dmarc_monitoring_only"]), verdict("b.example", "ERROR")]);
assert.deepEqual(r.changes, ["worse", "unknown"]);
assert.ok(r.report.alert.includes("a.example* went from PASS to WARN"));
assert.equal(memory.domains["b.example"].status, "FAIL"); // a failed lookup keeps the last real verdict

r = await run([verdict("a.example", "PASS"), verdict("b.example", "FAIL", ["dmarc_missing"], "v=spf1 include:new.example -all")]);
assert.deepEqual(r.changes, ["better", "changed"]);
assert.ok(r.report.alert.includes("different DNS records") && !r.report.alert.includes("a.example"));

// ---- docs/rules.md lists exactly the findings the rules node can produce ----
const rulesCode = wf.nodes.find((n) => n.name.startsWith("Rules:")).parameters.jsCode;
const inCode = [...rulesCode.matchAll(/add\('([a-z_]+)', '([a-z]+)'/g)].map((m) => m[1] + " " + m[2]).sort();
const inDoc = [...readFileSync("docs/rules.md", "utf8").matchAll(/^\| `([a-z_]+)` \| ([a-z]+) \|/gm)].map((m) => m[1] + " " + m[2]).sort();
assert.deepEqual(inDoc, inCode);

console.log("workflow nodes: all checks pass");
