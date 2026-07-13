# PLM Connector

PLM Connector bringt Projekte, Teile, Revisionen und kontrollierte Dateiabläufe
direkt in die CAD-Oberfläche.

![PLM Connector mit Projektbrowser und Revisionsdetails](https://git.home.schumbi.de/ralf/freecad-plm-addon/raw/branch/main/Resources/Media/plm-workbench-overview.png)

## Alles Wichtige an einem Ort

- Projekte und Teile durchsuchen und ihre Metadaten pflegen.
- Revisionen schreibgeschützt öffnen oder für Änderungen auschecken.
- Root-Dateien und referenzierte Modelle gemeinsam einchecken.
- Aktive Checkouts wieder öffnen oder kontrolliert abbrechen.
- Revisionsnotizen und Anmerkungen lesen und bearbeiten.
- Lokale Modellordner als Projektstand oder neues Projekt importieren.

Dateien werden anhand des Server-Manifests und ihrer SHA-256-Prüfsummen
übertragen. Unveränderte Modelle und rein technische Speicherartefakte erzeugen
keine unnötigen Revisionen.

## Schnellstart

1. Die Workbench **FreeCAD-PLM** auswählen.
2. **PLM-Verbindung aktivieren** öffnen.
3. Unter **Verbindungseinstellungen** Server-URL, API-Token und lokalen
   Workspace eintragen.
4. Ein Projekt, ein Teil und eine Revision auswählen.
5. Die Revision schreibgeschützt öffnen oder einen Checkout starten.

Der lokale Workspace enthält Checkouts und zwischengespeicherte Revisionen. Der
Server bleibt die verbindliche Quelle für Revisionen und Checkout-Sperren.

## Berechtigungen

| Scope | Ermöglicht |
| --- | --- |
| `read` | Projekte, Teile, Revisionen, Notizen und Anmerkungen lesen |
| `write` | Notizen und Anmerkungen bearbeiten |
| `checkout` | Modelle auschecken, einchecken und Checkouts abbrechen |
| `admin` | Projekte und Projektmetadaten anlegen oder bearbeiten |

Für Lesen, Checkout, Check-in, Notizen und Anmerkungen ist kein `admin`-Scope
nötig. Er wird nur für administrative Projektabläufe benötigt.

## Dokumentation

Das ausführliche
[Addon-Handbuch](https://git.home.schumbi.de/ralf/freecad-plm/wiki/FreeCAD-Addon-Handbuch)
beschreibt Konfiguration und Arbeitsabläufe im Detail.
