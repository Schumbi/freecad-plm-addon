# Changelog

## 0.1.9 – 2026-09-24

- Projekte über Text und mehrere Tags filtern: UND, ODER und Ohne Tags.
- Tags in den Projekteigenschaften bearbeiten, mit Vorschlägen vorhandener Namen.
- Ein Klick auf „Alle“ setzt Filter zurück; Direktnavigation kann ausgeblendete
  Projekte wieder sichtbar machen. Ältere Server ohne Tags bleiben nutzbar.

## 0.1.8 – 2026-09-23

- Die Druckprojekt-Auswahl zeigt alle Druckprojekte des gewählten PLM-Projekts über sämtliche Revisionen hinweg.
- Eigene Tabellenspalten zeigen Teil/FCStd-Datei, zugeordnete Revision und Vorschau.
- Beim Öffnen wird die Revision des gewählten Druckprojekts für Workspace und Quellen verwendet, unabhängig von der Baum-Auswahl.

## 0.1.7 – 2026-09-23

- Druckprojekte werden immer explizit ausgewählt: vorhandenen Slicerstand öffnen oder ein neues Projekt mit eigenem Code erstellen.
- Der Dialog zeigt verfügbare Plattenvorschaubilder neben den Projekten; Bilder werden im Hintergrund geladen.
- Normales Öffnen behält vorhandene Slicer-Geometrie bei. Neuaufbau erfolgt über die separate, bestätigte Aktion.

## 0.1.6 – 2026-09-23

- Der globale Deep-Link-Event-Filter lässt fremde Ereignisse direkt passieren. Das verhindert den PySide6-TypeError beim Weiterreichen von `QStandardItem` an `QObject.eventFilter`.
- Ein Regressionstest sichert ab, dass normale Ereignisse und FCStd-Dateiöffnungen weder abgefangen noch an die QObject-Basismethode übergeben werden.

## 0.1.5 – 2026-09-23

Änderungen seit 0.1.4:

- Bei unverändertem Checkout zeigt die Hauptaktion „Abbrechen“ statt „Einchecken“.
- Mehrere Druckprojekte derselben Revision lassen sich gezielt auswählen. Lokale Arbeitsordner und Synchronisationszustände sind je Druckprojekt getrennt.
- Die 3MF-Synchronisation übermittelt den bekannten Server-Hash, damit parallele Änderungen als Konflikt erkannt werden.
- Workspace-Pfade werden nach Windows- und Linux-Regeln geprüft; symbolische Links dürfen nicht aus dem Workspace führen.
- Authentifizierte Downloads sind auf den PLM-Ursprung begrenzt. Fehlgeschlagene Downloads erhalten vorhandene Dateien.
- Das große Panel-Modul ist in kleinere Module für Projektbrowser, Projekte, Teile, Anmerkungen, Druckprojekte und Checkouts aufgeteilt.
- Dokumentation und Regressionstests wurden erweitert.
