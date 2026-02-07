# Visual Studio Code + Claude Code Setup Guide

## Für den Entwicklungsprozess mit Claude Code Plugin

### Schritt 1: Repository vorbereiten

```bash
# Repository in VS Code öffnen
cd /path/to/netbird-msp-appliance
code .
```

### Schritt 2: Claude Code Plugin installieren

1. Öffne VS Code Extensions (Ctrl+Shift+X)
2. Suche nach "Claude Code"
3. Installiere das Plugin
4. Authentifiziere dich mit deinem Anthropic Account

### Schritt 3: Claude Code verwenden

#### Hauptaufgabe an Claude geben:

Öffne Claude Code Chat und schicke folgende Nachricht:

```
Bitte lies die Datei CLAUDE_CODE_SPEC.md und implementiere das komplette NetBird MSP Appliance Projekt gemäß den Spezifikationen.

Prioritäten:
1. Erstelle zuerst die komplette Dateistruktur
2. Implementiere die Datenbank-Modelle und API-Routers
3. Baue die Services (docker_service, npm_service, netbird_service)
4. Erstelle die Jinja2 Templates
5. Baue das Frontend (HTML/CSS/JS)
6. Füge Tests hinzu

Achte besonders auf:
- Type hints in allen Python-Funktionen
- Comprehensive Error Handling
- Docstrings für alle Funktionen
- Clean Code und Modularität
- Security Best Practices

Beginne mit der Implementierung!
```

### Schritt 4: Iteratives Entwickeln

Claude Code wird Schritt für Schritt:

1. **Struktur erstellen**
   - Alle Verzeichnisse anlegen
   - Basis-Dateien erstellen
   - Dependencies auflisten

2. **Backend implementieren**
   - Database Models
   - API Routers
   - Services
   - Utils

3. **Templates erstellen**
   - docker-compose.yml.j2
   - management.json.j2
   - relay.env.j2

4. **Frontend bauen**
   - HTML Dashboard
   - CSS Styling
   - JavaScript Logic

5. **Testen & Debugging**
   - Unit Tests
   - Integration Tests
   - Manuelle Tests

### Schritt 5: Spezifische Anweisungen

Du kannst Claude Code auch spezifische Aufgaben geben:

```
"Implementiere jetzt den docker_service.py mit allen Funktionen 
zum Starten, Stoppen und Überwachen von Docker-Containern"
```

```
"Erstelle das Frontend Dashboard mit Bootstrap 5 und mache es 
responsive für Mobile/Tablet/Desktop"
```

```
"Füge comprehensive Error Handling zum Deployment-Prozess hinzu 
mit automatischem Rollback bei Fehlern"
```

### Schritt 6: Code Review

Nach jeder größeren Implementierung:

```
"Bitte reviewe den Code in app/services/docker_service.py und 
verbessere Error Handling und füge Type Hints hinzu"
```

### Schritt 7: Testing

```
"Erstelle Unit Tests für alle Services und API-Endpunkte"
```

### Schritt 8: Dokumentation

```
"Erstelle API-Dokumentation und ergänze die README mit 
Deployment-Beispielen"
```

## Tipps für effektive Zusammenarbeit mit Claude Code

### ✅ Gute Anweisungen:
- "Implementiere X gemäß der Spezifikation in CLAUDE_CODE_SPEC.md"
- "Füge Error Handling für Y hinzu"
- "Refactore Z für bessere Wartbarkeit"
- "Erstelle Tests für Modul A"

### ❌ Vermeiden:
- Zu vage Anweisungen ohne Kontext
- Mehrere komplexe Aufgaben gleichzeitig
- Widersprüchliche Requirements

## Debugging mit Claude Code

```
"Der Deployment-Prozess schlägt fehl mit diesem Fehler: [Fehlermeldung]. 
Bitte analysiere das Problem und fixe es."
```

```
"Die NPM-Integration funktioniert nicht. Logs zeigen: [Logs]. 
Was ist das Problem?"
```

## Projekt-Struktur prüfen

Claude Code kann die Struktur validieren:

```
"Überprüfe, ob alle Dateien gemäß CLAUDE_CODE_SPEC.md 
vorhanden und korrekt strukturiert sind"
```

## Abschließende Checks

```
"Führe folgende Checks durch:
1. Alle Dependencies in requirements.txt?
2. Docker-Compose gültig?
3. Alle Environment Variables dokumentiert?
4. README vollständig?
5. Installation Script funktional?"
```

## Deployment vorbereiten

```
"Bereite das Projekt für Production Deployment vor:
1. Sicherheits-Audit
2. Performance-Optimierungen
3. Logging verbessern
4. Monitoring Endpoints hinzufügen"
```

---

## Erwartete Entwicklungszeit mit Claude Code

- **Basis-Struktur**: 10-15 Minuten
- **Backend (APIs + Services)**: 30-45 Minuten  
- **Templates**: 10-15 Minuten
- **Frontend**: 30-45 Minuten
- **Tests**: 20-30 Minuten
- **Dokumentation & Polish**: 15-20 Minuten

**Gesamt: ~2-3 Stunden** für ein vollständiges, produktionsreifes System!

---

## Nach der Entwicklung

### Lokales Testen:

```bash
# Docker Compose starten
docker compose up -d

# Logs prüfen
docker logs -f netbird-msp-appliance

# In Browser öffnen
http://localhost:8000
```

### Auf VM deployen:

```bash
# Repository auf VM clonen
git clone https://github.com/yourusername/netbird-msp-appliance.git
cd netbird-msp-appliance

# Installer ausführen
chmod +x install.sh
sudo ./install.sh
```

Viel Erfolg! 🚀
