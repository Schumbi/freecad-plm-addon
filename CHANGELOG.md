# Changelog

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
