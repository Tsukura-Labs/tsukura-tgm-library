# Tsukura TGM Library / TGM-Bibliothek

**EN** - Public, community-maintained collection of devices for the Tsukura Device Manager (TGM):
TGM device scripts with sounds, banks and control panels. Browse it at `tsukura.media/devices/`
or inside TGM (button "Show online library": online devices appear in the normal tree). Entries are submitted from TGM with a tsukura.media account,
reviewed by an admin and committed here by the server - you do not need a GitHub account.

**DE** - Oeffentliche Sammlung von Geraeten fuer den Tsukura Geraete Manager (TGM): Klaenge, Baenke,
Bedienoberflaechen (TGM-Geraetescripts). Ansehen unter `tsukura.media/devices/` oder in TGM
(Knopf "Online-Bibliothek anzeigen": Online-Geraete erscheinen im normalen Baum). Eintraege werden in TGM mit dem tsukura.media-Konto eingereicht, von einem Admin
geprueft und vom Server hier eingetragen - ein GitHub-Konto ist nicht noetig.

## Layout

```
devices/<manufacturer-slug>/<device-slug>/
    device.json      device, banks, authors, sound packs, presets (tgm.device/1)
    panel.json       control panels, optional (tgm.panels/1)
    images/          device photo / panel image (png|jpg, max 2 MB each)
manufacturers.json   canonical manufacturer list ("did you mean ...?")
schema/              JSON schemas (device, panels, index)
examples/            tiny example device used by the self-test (NOT published)
.github/             workflow + scripts/build_index.py
```

Slugs use only `a-z`, `0-9` and `-`. The device id is `<manufacturer-slug>/<device-slug>`.

## Automatic packages / Automatische Pakete

Every push to `main` runs `.github/workflows/packages.yml`: validate, one ZIP per changed device
(`<manufacturer>-<device>-v<version>.zip`), upload to the release tag `packages`, then publish
`index.json` (`tgm.index/1`) there. TGM and the website only download these packages.
Pure Python standard library; local check: `python .github/scripts/build_index.py --self-test`
and `python .github/scripts/build_index.py --validate-only`.

## License / Lizenz

All data in this repository is released under **CC0 1.0** (public domain dedication), see `LICENSE`.
Only submit content you are allowed to publish (own work or free content - no commercial factory
presets that are not yours). Alle Daten stehen unter **CC0 1.0**, siehe `LICENSE`; reiche nur Inhalte
ein, die du veroeffentlichen darfst.

### Imported Cubase patch name lists / Uebernommene Cubase-Klanglisten

**EN** - Some devices were converted from the patch name scripts shipped with Steinberg Cubase (pure lists
of the factory sound names and their program/bank numbers). The CC0 dedication above covers the work of
this repository; it does not take away the credit of the original script authors. Each such device names
its source script and author in its `description`. Rights holders who object can open an issue and the
device will be removed.

**DE** - Einige Geraete wurden aus den mit Steinberg Cubase mitgelieferten Patchname-Skripten uebernommen
(reine Listen der Werksklang-Namen mit Programm-/Banknummern). Die CC0-Widmung oben gilt fuer die Arbeit
dieser Sammlung; die Nennung der urspruenglichen Skript-Ersteller bleibt erhalten. Jedes solche Geraet nennt
Quell-Skript und Ersteller in seiner `description`. Rechteinhaber, die widersprechen, koennen ein Issue
eroeffnen; das Geraet wird dann entfernt.

### Device photos / Geraetefotos

**EN** - Some device photos (`images/device.jpg`) come from Wikimedia Commons. They are NOT covered by the
CC0 dedication: each keeps its own free license (public domain, CC0, CC BY or CC BY-SA). Photographer,
license and source page are named at the end of the device's `description`. Reuse them under their license.

**DE** - Einige Geraetefotos (`images/device.jpg`) stammen von Wikimedia Commons. Sie fallen NICHT unter die
CC0-Widmung, sondern behalten ihre eigene freie Lizenz (gemeinfrei, CC0, CC BY oder CC BY-SA). Fotograf,
Lizenz und Quellseite stehen am Ende der `description` des Geraets. Weiterverwendung nur nach dieser Lizenz.
