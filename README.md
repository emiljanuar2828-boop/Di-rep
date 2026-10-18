# Federwerk

Eine deutschsprachige Web-App, die handgeschriebene Vorlagen mit OpenCV erkennt und als installierbaren TrueType- (`.ttf`) und OpenType-Font (`.otf`) ausgibt. Bis zu drei unterschiedliche Schreibproben pro Zeichen werden als echte OpenType-`calt`-Kontextalternativen eingebettet.

## Start

Voraussetzung: Python 3.10 oder neuer.

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python app.py
```

Die Anwendung öffnet sich unter <http://localhost:5000>. Für einen anderen Port kann die Umgebungsvariable `PORT` gesetzt werden.

## Arbeitsablauf

1. Die automatisch generierte, druckbare dreiseitige PDF-Vorlage mit 101 Zeichen und bis zu drei Proben je Zeichen herunterladen.
2. Alle drei Seiten als PNG, JPG oder WebP hochladen, den Bildern die passenden Vorlagenseiten zuweisen und die Schriftfelder ausfüllen. Die Erkennung korrigiert Schräglage und isoliert die Tintenstriche der einzelnen Vorlagelücken.
3. Erkannte Schriftzüge prüfen, Zeichen bei Bedarf umbenennen und Alternativformen vergleichen.
4. Den erzeugten Font in einem editierbaren Textfeld testen und echte TTF- beziehungsweise CFF-/OTF-Dateien herunterladen.

Unterstützte Zeichen: `A–Z`, `ÄÖÜ`, `a–z`, `äöüß`, `0–9` sowie druckbare ASCII-Satz- und Sonderzeichen. Pro exportiertem Zeichen ist mindestens eine lesbare Handschriftprobe erforderlich. Großbuchstaben und Ziffern sind ebenfalls Teil des Fonts.

## Daten & Verarbeitung

Fotoerkennung und Font-Erstellung laufen auf dem App-Server; es werden keine externen OCR- oder KI-Anbieter benötigt. Die Zeichnungen werden in einem flüchtigen In-Memory-Arbeitsspeicher für eine Stunde zur Vorschau und für den Download vorgehalten. Dateien oder Nutzerkonten werden nicht dauerhaft gespeichert.
