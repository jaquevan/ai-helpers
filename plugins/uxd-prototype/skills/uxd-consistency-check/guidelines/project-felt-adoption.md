---
id: project-felt-adoption
title: Project Felt Adoption
category: foundations
automatable: true
checkpoints: [local, mr, signoff]
severity: error
---

# Project Felt Adoption

## Rule

Red Hat portfolio prototypes must apply the Project Felt theme at the root
`<html>` element and use Felt-specific background assets where the application
uses PatternFly glass backgrounds. Do not mix Felt with explicit default-theme
background assets or default-theme markers.

## Automated Checks

The source analyzer checks each app entry document for the `pf-v6-theme-felt`
root class, checks authored source and available PatternFly assets for
`Felt-Bkg-Generic-Light.svg` or `Felt-Bkg-Generic-Dark.svg`, and reports
explicit references to default `PF-Bkg-Generic-*` assets or default-theme
markers.

## Manual Review Checklist

- [ ] The root `<html>` element includes `pf-v6-theme-felt`.
- [ ] PatternFly glass backgrounds use the Felt light or dark asset.
- [ ] No default PatternFly background asset is explicitly mixed into the Felt theme.
- [ ] Browser checks show pill-shaped controls and Red Hat red primary accents.
