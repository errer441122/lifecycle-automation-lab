# Email copy

Copy for all seven emails, ready to paste into the Klaviyo template editor.
Subject lines and internal names are already set on the flow actions; what is
below is the body.

Every email must keep the footer that Klaviyo injects — the physical address
and the one-click unsubscribe are not optional, and removing them breaks both
the GDPR position in [`consent.md`](consent.md) and the Gmail/Yahoo bulk-sender
rules in [`deliverability.md`](deliverability.md).

Merge tags use Klaviyo syntax. `{{ first_name|default:'' }}` degrades to an
empty string rather than printing the tag when the field is missing — the
single most common visible bug in a first send.

---

## Flow 1 — Welcome

### 1.1 · Day 0 · *Benvenuto in Torrefazione Nord*

> Ciao {{ first_name|default:'' }},
>
> grazie per aver confermato l'iscrizione. Confermare è un passaggio in più, lo
> sappiamo, e serve a una cosa sola: essere certi che tu voglia davvero sentirci.
>
> **Cosa aspettarti**
> Ti scriviamo circa due volte al mese. Niente sconti a raffica: quando arriva
> un caffè nuovo te lo raccontiamo, e ogni tanto ti mandiamo qualcosa di utile
> sull'estrazione.
>
> **Chi siamo**
> Tostiamo a Bologna, in piccoli lotti. Ogni sacchetto riporta origine, data di
> tostatura e note di degustazione.
>
> Se cambi idea, il link per disiscriverti è in fondo a ogni email e funziona
> al primo clic.
>
> [Scopri le monorigine →]

**Perché così.** Dichiarare la frequenza in apertura è il modo più economico di
ridurre le disiscrizioni successive: chi resta sa cosa ha accettato. Citare
l'unsubscribe qui sembra controintuitivo, ma abbassa i reclami spam — e sotto
lo 0,3% ci si deve stare per forza.

### 1.2 · Day 3 · *Da dove iniziare: i nostri tre caffè più scelti*

> {{ first_name|default:'' }}, se è la prima volta che compri caffè in grani la
> scelta può paralizzare. Questi tre coprono quasi tutti i gusti.
>
> **Etiopia Yirgacheffe** — bergamotto, gelsomino, tè nero. Tostatura chiara,
> dà il meglio in filtro. *Se ti piace il tè.*
>
> **Brasile Cerrado** — cioccolato fondente, mandorla, panna. Corpo pieno,
> bassa acidità. *Se il caffè lo bevi con il latte.*
>
> **Miscela Espresso Bar** — 70% arabica, 30% robusta. Crema persistente.
> *Se hai la macchina a leva.*
>
> Non riesci a scegliere? Il **Set degustazione 4x100g** li mette a confronto
> senza impegnarti su un sacchetto intero.
>
> [Vedi il set degustazione →]

**Perché così.** Ogni prodotto è legato a una situazione del lettore, non a un
aggettivo. Il set in chiusura è l'offerta a minor attrito per chi non sa
decidere.

---

## Flow 2 — Abandoned cart

Nessuna delle tre contiene uno sconto. Uno sconto prevedibile
sull'abbandono insegna ad abbandonare: se lo sconto va fatto, va testato con un
gruppo di controllo, non regalato di default.

### 2.1 · 4 ore dopo · *Hai lasciato qualcosa nel carrello*

> {{ first_name|default:'' }}, il tuo carrello è ancora qui.
>
> {% for item in event.extra.line_items %}
> **{{ item.title }}** — {{ item.quantity }} × {{ item.price }}
> {% endfor %}
>
> Lo teniamo da parte, ma le scorte no: alcune monorigine escono in lotti
> piccoli e finiscono.
>
> [Riprendi l'ordine →]

**Perché 4 ore.** Prende la stessa sessione o la stessa serata, quando il
motivo dell'abbandono — una distrazione, non un ripensamento — è ancora
reversibile. È anche il ritardo che vale la pena testare per primo contro 1 ora.

### 2.2 · 20 ore dopo · *Spedizione in 48h e reso gratuito entro 14 giorni*

> Ti è rimasto un dubbio, {{ first_name|default:'' }}? I tre più comuni:
>
> **Quanto ci mette?** 48 ore in tutta Italia. Tostiamo il lunedì e il giovedì,
> quindi il caffè che ricevi ha meno di una settimana.
>
> **E se non mi piace?** Reso gratuito entro 14 giorni, anche a sacchetto
> aperto. Il caffè è questione di gusti, non ha senso far finta di no.
>
> **Come pago?** Carta, PayPal, Apple Pay. Nessun account da creare.
>
> [Completa l'ordine →]

**Perché così.** La seconda email non ripete la richiesta: risponde
all'obiezione. Ripetere "hai lasciato qualcosa" dopo venti ore è rumore.

### 2.3 · 2 giorni dopo · *Ultimo promemoria: il tuo carrello sta per scadere*

> {{ first_name|default:'' }}, questo è l'ultimo messaggio sul tuo carrello —
> poi lo lasciamo andare e non ti scriviamo più a riguardo.
>
> {% for item in event.extra.line_items %}
> **{{ item.title }}**
> {% endfor %}
>
> Se hai cambiato idea va benissimo. Se invece era solo il momento sbagliato,
> è ancora tutto qui.
>
> [Riprendi l'ordine →]

**Perché così.** Dire esplicitamente che è l'ultimo messaggio, e poi
mantenerlo, è ciò che rende il flow tollerabile. Il tono ammette che non
comprare è una risposta legittima.

---

## Flow 3 — Win-back

### 3.1 · All'ingresso nel segmento · *È passato un po'. Il tuo caffè ti aspetta*

> {{ first_name|default:'' }}, l'ultima volta hai preso
> {{ person.last_product|default:'un nostro caffè' }}. Sono passati un po' di
> mesi — se hai finito la scorta senza accorgertene, capita.
>
> Nel frattempo è cambiato qualcosa: le origini ruotano con il raccolto, quindi
> il profilo che ti piaceva potrebbe avere una versione nuova.
>
> [Rivedi cosa hai preso →]

**Perché così.** Nessuno sconto in prima battuta. Il primo tentativo verifica
se serve solo un promemoria — e per un prodotto di consumo spesso è così. Se
funziona senza sconto, il margine resta.

### 3.2 · 7 giorni dopo · *Un motivo in più per tornare*

> {{ first_name|default:'' }}, ci proviamo una volta sola: **-15% sul prossimo
> ordine**, codice `TORNA15`, valido 14 giorni.
>
> Se non fa per te nessun problema — non insistiamo oltre e questa è l'ultima
> email di riattivazione che ricevi.
>
> [Usa il codice →]

**Perché così.** Una sola offerta, dichiarata come unica, e poi silenzio. Un
win-back che insiste produce reclami spam, non ordini. Chi non risponde a
questa passa alla traccia a bassa frequenza descritta in
[`flows.md`](flows.md), e da lì al sunset.

---

## Prima di pubblicare

- [ ] Sostituire `TORNA15` con un codice sconto vero creato in Shopify
- [ ] Verificare che i merge tag rendano su un invio di prova, non in anteprima
- [ ] Controllare i blocchi prodotto dinamici del carrello con un ordine reale
- [ ] Le affermazioni concrete — 48h di spedizione, reso a 14 giorni, tostatura
      lunedì e giovedì — sono **placeholder plausibili, non impegni verificati**.
      Vanno allineate alla realtà del negozio prima di qualunque invio, o
      diventano pubblicità ingannevole.
