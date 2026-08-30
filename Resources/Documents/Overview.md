# PLM Connector

PLM Connector bringt Projekte, Teile, Revisionen und kontrollierte Dateiabläufe
direkt in die CAD-Oberfläche.

![PLM Connector mit Projektbrowser und Revisionsdetails](https://git.home.schumbi.de/ralf/freecad-plm-addon/raw/branch/main/Resources/Media/plm-workbench-overview.png)

## Alles Wichtige an einem Ort

- Projekte und Teile durchsuchen und ihre Metadaten pflegen.
- Revisionen schreibgeschützt öffnen oder für Änderungen auschecken.
- Root-Dateien und referenzierte Modelle gemeinsam einchecken.
- Aktive Checkouts wieder öffnen oder kontrolliert abbrechen.
- Neue FreeCAD-Teile mit `R0001` anlegen und direkt öffnen, ohne zuvor eine lokale Datei speichern zu müssen.
- Revisionsnotizen und Anmerkungen lesen und bearbeiten.
- Lokale Modellordner mit FCStd-, STEP- und STL-Dateien als Projektstand oder neues Projekt importieren.
- Revisionsaktionen aus der Web-Oberfläche über `freecad-plm://` direkt in
  FreeCAD öffnen, unter Linux und Windows sowie auch bei schon laufendem
  FreeCAD.

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

Beim FreeCAD-Start registriert das Addon den Web-Link-Handler automatisch für
den aktuellen Linux- oder Windows-Benutzer. Falls ein Browserlink nicht mehr
reagiert, kann die Zuordnung über `FreeCAD-PLM -> Web-Link-Handler einrichten`
erneuert werden.

Für ein neues FreeCAD-Modell genügt **Neues Teil**: Name, optionale
Teilenummer und Typ eingeben und **Anlegen und öffnen** wählen. Das Addon
erzeugt die FCStd-Datei intern. Bei geöffnetem Projekt-Checkout wird sie dort
als `R0001` ergänzt, andernfalls in einem eigenen Checkout geöffnet.

Der lokale Workspace enthält Checkouts und zwischengespeicherte Revisionen. Der
Server bleibt die verbindliche Quelle für Revisionen und Checkout-Sperren.

STEP- und STL-Revisionen können schreibgeschützt geöffnet werden. Bearbeitbare Checkouts und Check-ins bleiben FCStd-Modellen vorbehalten.

## Berechtigungen

| Scope | Ermöglicht |
| --- | --- |
| `read` | Projekte, Teile, Revisionen, Notizen und Anmerkungen lesen |
| `write` | Teile anlegen/bearbeiten, importieren sowie Notizen und Anmerkungen bearbeiten |
| `checkout` | Modelle auschecken, einchecken, abbrechen und neue FCStd-Teile direkt öffnen |
| `admin` | Projekte und Projektmetadaten anlegen oder bearbeiten |

Für normale CAD-Arbeit einschließlich Teilanlage sind `read`, `write` und
`checkout` ausreichend. `admin` wird nur für Projektanlage und administrative
Projektabläufe benötigt.

## Dokumentation

Das ausführliche
[Addon-Handbuch](https://git.home.schumbi.de/ralf/freecad-plm/wiki/FreeCAD-Addon-Handbuch)
beschreibt Konfiguration und Arbeitsabläufe im Detail.
