"""Build the seven flow email templates in Klaviyo from the copy in docs/.

Klaviyo's drag-and-drop editor has no HTML view, so assembling seven emails by
hand means roughly nine block operations each. The Templates API accepts raw
HTML, so the layout is expressed here once and every email is generated from
the same function. Editing the copy below and re-running is faster, and more
reviewable, than clicking through the editor again.

The HTML is deliberately plain: a single centred column, tables rather than
flexbox, inline styles, no images and no web fonts. That is not minimalism for
its own sake — Outlook still renders with Word's engine, images are blocked by
default in most clients on first open, and this project has no brand imagery to
show anyway. An email that says everything it needs to in text survives all of
that.

`{% unsubscribe %}` is mandatory. A custom HTML template does not inherit
Klaviyo's footer, so without that tag the send would breach both the consent
design in docs/consent.md and the one-click unsubscribe requirement in
docs/deliverability.md.

After running this, assign each template to its flow message in Klaviyo:
Flows -> the flow -> the email -> Change template.

Pure standard library.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

API_ROOT = "https://a.klaviyo.com/api/templates"
API_REVISION = "2026-07-15"

BRAND = "Torrefazione Nord"
SITE = "https://negozio-1-om2cqkph.myshopify.com"

# Copy mirrors docs/email-copy.md. Kept as data rather than parsed out of the
# markdown: a parser tied to heading levels breaks the moment the document is
# reorganised, and the document is written for people, not for a machine.
EMAILS: list[dict] = [
    {
        "key": "1.1",
        "name": "1.1 Benvenuto + cosa aspettarti",
        "preheader": "Cosa aspettarti da noi, e ogni quanto ti scriviamo.",
        "heading": "Benvenuto in Torrefazione Nord",
        "body": [
            "Ciao {{ first_name|default:'' }}, grazie per aver confermato "
            "l'iscrizione. Confermare e un passaggio in piu, lo sappiamo, e "
            "serve a una cosa sola: essere certi che tu voglia davvero sentirci.",
            "<b>Cosa aspettarti.</b> Ti scriviamo circa due volte al mese. "
            "Niente sconti a raffica: quando arriva un caffe nuovo te lo "
            "raccontiamo, e ogni tanto ti mandiamo qualcosa di utile "
            "sull'estrazione.",
            "<b>Chi siamo.</b> Tostiamo a Bologna, in piccoli lotti. Ogni "
            "sacchetto riporta origine, data di tostatura e note di degustazione.",
            "Se cambi idea, il link per disiscriverti e in fondo a ogni email e "
            "funziona al primo clic.",
        ],
        "cta": ("Scopri le monorigine", f"{SITE}/collections/all"),
    },
    {
        "key": "1.2",
        "name": "1.2 Orientamento - i piu scelti",
        "preheader": "Tre caffe che coprono quasi tutti i gusti.",
        "heading": "Da dove iniziare",
        "body": [
            "{{ first_name|default:'' }}, se e la prima volta che compri caffe "
            "in grani la scelta puo paralizzare. Questi tre coprono quasi tutti "
            "i gusti.",
            "<b>Etiopia Yirgacheffe</b> — bergamotto, gelsomino, te nero. "
            "Tostatura chiara, da il meglio in filtro. <i>Se ti piace il te.</i>",
            "<b>Brasile Cerrado</b> — cioccolato fondente, mandorla, panna. "
            "Corpo pieno, bassa acidita. <i>Se il caffe lo bevi con il latte.</i>",
            "<b>Miscela Espresso Bar</b> — 70% arabica, 30% robusta. Crema "
            "persistente. <i>Se hai la macchina a leva.</i>",
            "Non riesci a scegliere? Il Set degustazione 4x100g li mette a "
            "confronto senza impegnarti su un sacchetto intero.",
        ],
        "cta": ("Vedi il set degustazione", f"{SITE}/collections/all"),
    },
    {
        "key": "2.1",
        "name": "2.1 Ancora interessato?",
        "preheader": "Il tuo carrello e ancora qui.",
        "heading": "Hai lasciato qualcosa nel carrello",
        "body": [
            "{{ first_name|default:'' }}, il tuo carrello e ancora qui.",
            "Lo teniamo da parte, ma le scorte no: alcune monorigine escono in "
            "lotti piccoli e finiscono.",
        ],
        "cta": ("Riprendi l'ordine", "{{ event.extra.checkout_url }}"),
    },
    {
        "key": "2.2",
        "name": "2.2 Rassicurazione - spedizione e resi",
        "preheader": "Spedizione in 48h e reso gratuito entro 30 giorni.",
        "heading": "Ti e rimasto un dubbio?",
        "body": [
            "<b>Quanto ci mette?</b> 48 ore in tutta Italia. Tostiamo il lunedi "
            "e il giovedi, quindi il caffe che ricevi ha meno di una settimana.",
            "<b>E se non mi piace?</b> Reso gratuito entro 30 giorni, spedizione "
            "di reso a carico nostro. Il caffe e questione di gusti, non ha "
            "senso far finta di no.",
            "<b>Devo creare un account?</b> No, puoi ordinare come ospite.",
        ],
        "cta": ("Completa l'ordine", "{{ event.extra.checkout_url }}"),
    },
    {
        "key": "2.3",
        "name": "2.3 Ultimo promemoria",
        "preheader": "Ultimo messaggio sul tuo carrello.",
        "heading": "Il tuo carrello sta per scadere",
        "body": [
            "{{ first_name|default:'' }}, questo e l'ultimo messaggio sul tuo "
            "carrello — poi lo lasciamo andare e non ti scriviamo piu a riguardo.",
            "Se hai cambiato idea va benissimo. Se invece era solo il momento "
            "sbagliato, e ancora tutto qui.",
        ],
        "cta": ("Riprendi l'ordine", "{{ event.extra.checkout_url }}"),
    },
    {
        "key": "3.1",
        "name": "3.1 E passato un po",
        "preheader": "Se hai finito la scorta senza accorgertene, capita.",
        "heading": "E passato un po'",
        "body": [
            "{{ first_name|default:'' }}, sono passati alcuni mesi dal tuo "
            "ultimo ordine. Se hai finito la scorta senza accorgertene, capita.",
            "Nel frattempo e cambiato qualcosa: le origini ruotano con il "
            "raccolto, quindi il profilo che ti piaceva potrebbe avere una "
            "versione nuova.",
        ],
        "cta": ("Rivedi cosa hai preso", f"{SITE}/collections/all"),
    },
    {
        "key": "3.2",
        "name": "3.2 Offerta di riattivazione (unica)",
        "preheader": "Una sola offerta, poi non insistiamo.",
        "heading": "Un motivo in piu per tornare",
        "body": [
            "{{ first_name|default:'' }}, ci proviamo una volta sola: "
            "<b>-15% sul prossimo ordine</b>, codice <b>TORNA15</b>, valido 14 "
            "giorni.",
            "Se non fa per te nessun problema — non insistiamo oltre e questa e "
            "l'ultima email di riattivazione che ricevi.",
        ],
        "cta": ("Usa il codice", f"{SITE}/collections/all"),
    },
]


def render_html(email: dict) -> str:
    """One centred column, tables and inline styles, no images."""
    paragraphs = "\n".join(
        f'<p style="margin:0 0 16px;font-size:16px;line-height:1.6;'
        f'color:#303b43;">{p}</p>'
        for p in email["body"]
    )
    cta_text, cta_url = email["cta"]
    return f"""<!doctype html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{email["heading"]}</title>
</head>
<body style="margin:0;padding:0;background:#f4f2ef;">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;">
{email["preheader"]}
</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
       style="background:#f4f2ef;">
  <tr><td align="center" style="padding:32px 12px;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
           style="max-width:560px;background:#ffffff;border-radius:4px;">
      <tr><td style="padding:32px 32px 8px;">
        <p style="margin:0;font-size:13px;letter-spacing:.08em;
                  text-transform:uppercase;color:#8a8279;">{BRAND}</p>
      </td></tr>
      <tr><td style="padding:0 32px 16px;">
        <h1 style="margin:0;font-size:26px;line-height:1.25;color:#1d2429;
                   font-weight:700;">{email["heading"]}</h1>
      </td></tr>
      <tr><td style="padding:0 32px 8px;">
{paragraphs}
      </td></tr>
      <tr><td style="padding:16px 32px 32px;">
        <a href="{cta_url}"
           style="display:inline-block;padding:14px 28px;background:#303b43;
                  color:#ffffff;text-decoration:none;border-radius:4px;
                  font-size:16px;font-weight:700;">{cta_text}</a>
      </td></tr>
    </table>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
           style="max-width:560px;">
      <tr><td style="padding:20px 32px;text-align:center;font-size:12px;
                     line-height:1.6;color:#8a8279;">
        <p style="margin:0 0 8px;">{BRAND} — Bologna, Italia</p>
        <p style="margin:0;">
          Ricevi questa email perche hai confermato l'iscrizione.
          <a href="{{% unsubscribe %}}" style="color:#8a8279;">Disiscriviti</a>
          in un clic.
        </p>
      </td></tr>
    </table>
  </td></tr>
</table>
</body>
</html>"""


def render_text(email: dict) -> str:
    """Plain-text alternative. Required by docs/deliverability.md."""
    body = "\n\n".join(re.sub(r"<[^>]+>", "", p) for p in email["body"])
    cta_text, cta_url = email["cta"]
    return (
        f"{email['heading']}\n\n{body}\n\n{cta_text}: {cta_url}\n\n"
        f"{BRAND} — Bologna, Italia\n"
        "Ricevi questa email perche hai confermato l'iscrizione. "
        "Disiscriviti: {% unsubscribe %}"
    )


def create_template(email: dict, api_key: str, live: bool) -> str | None:
    body = {
        "data": {
            "type": "template",
            "attributes": {
                "name": email["name"],
                "editor_type": "CODE",
                "html": render_html(email),
                "text": render_text(email),
            },
        }
    }
    if not live:
        print(f"  [dry-run] {email['name']} — {len(body['data']['attributes']['html'])} bytes not sent")
        return None
    req = urllib.request.Request(
        API_ROOT,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Klaviyo-API-Key {api_key}",
            "Content-Type": "application/vnd.api+json",
            "Accept": "application/vnd.api+json",
            "revision": API_REVISION,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        sys.exit(f"Klaviyo rejected {email['name']} ({exc.code}): {detail}")
    tid = payload.get("data", {}).get("id", "created")
    print(f"  created {email['name']} -> {tid}")
    return tid


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--live", action="store_true",
                   help="actually call Klaviyo; without it nothing leaves the machine")
    p.add_argument("--out", type=Path, default=None,
                   help="also write the rendered HTML to this directory for review")
    args = p.parse_args(argv)

    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        for e in EMAILS:
            (args.out / f"{e['key']}.html").write_text(render_html(e), encoding="utf-8")
        print(f"HTML written to {args.out}\n")

    # Read from the environment, never a flag: a key on the command line ends
    # up in shell history and in `ps`.
    api_key = os.environ.get("KLAVIYO_API_KEY", "")
    if args.live and not api_key:
        sys.exit("KLAVIYO_API_KEY is not set - refusing to run --live.")

    print(f"{'LIVE' if args.live else 'DRY RUN'}: {len(EMAILS)} templates")
    for e in EMAILS:
        create_template(e, api_key, args.live)

    if not args.live:
        print("\nNothing was sent. Re-run with --live to create them in Klaviyo.")
    else:
        print("\nNow assign each one: Flows -> flow -> email -> Change template.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
