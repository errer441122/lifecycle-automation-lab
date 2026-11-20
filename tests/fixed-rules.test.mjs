// Runs the n8n "Rules: Fixed Checks (No AI)" Code node against the page's example drafts.
import { readFileSync } from "node:fs";
import assert from "node:assert/strict";

const wf = JSON.parse(readFileSync(process.argv[2] || "workflows/ai-email-preflight-qa.n8n.json", "utf8"));
const code = wf.nodes.find((n) => n.name === "Rules: Fixed Checks (No AI)").parameters.jsCode;
const run = (body) => new Function("$json", code)({ body }).json;
const cats = (list) => list.map((x) => x.category);
const unsub = " {% unsubscribe %}";

// Win-back, first draft: empty fallback, no UTMs, long subject, no preview.
let r = run({
  subject: "Torna a trovarci oggi: un regalo speciale per te con spedizione 48h!",
  preheader: "",
  html: `<p>Ciao {{ first_name|default:'' }}, spedizione garantita in 48 ore.</p><a href="https://negozio-online.org/collezione">Scopri</a>${unsub}`,
});
assert.deepEqual(cats(r.rule_blockers), ["personalization", "utm"]);
assert.deepEqual(cats(r.rule_warnings), ["mobile_ux", "preview_text"]);

// Black Friday and the fixed win-back: nothing for the rules to find.
for (const html of [
  `<p>Ciao Giulia,</p><a href="https://negozio-online.org/black-friday?utm_source=klaviyo&utm_medium=email&utm_campaign=promo_bf_2026">Vai</a>${unsub}`,
  `<p>Ciao{% if first_name %} {{ first_name }}{% endif %},</p><a href="https://negozio-online.org/collezione?utm_source=klaviyo&utm_medium=email&utm_campaign=lifecycle_winback">Esplora</a>${unsub}`,
]) {
  r = run({ subject: "Black Friday: 20% sulla nuova collezione", preheader: "Solo fino a domenica sera.", html });
  assert.deepEqual(r.rule_blockers, []);
  assert.deepEqual(r.rule_warnings, []);
}

// Edge cases: real fallback ok, template URL skipped, uppercase UTM, http link, missing unsubscribe, image without alt.
r = run({
  subject: "Ciao",
  preheader: "Una riga in piu",
  html: `{{ first_name|default:"amico" }} <a href="{{ event.extra.checkout_url }}">Carrello</a> <a href="https://x.it/?utm_source=Klaviyo&utm_medium=email&utm_campaign=a">A</a> <a href="http://x.it">B</a> <img src="p.png">`,
});
assert.deepEqual(cats(r.rule_blockers), ["utm", "links", "unsubscribe"]);
assert.deepEqual(cats(r.rule_warnings), ["accessibility"]);
console.log("rules node: all checks pass");
