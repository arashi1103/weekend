# Hong Kong Weekend Map 🗺️🚀

An automated web application and data pipeline designed to compile, visualize, and map out unique weekend destinations and activities across Hong Kong. 

This repository functions as a lightweight Progressive Web App (PWA) that dynamically updates its map layers through backend automated Python workflows.

---

## ✨ Features

* **Interactive Geospatial Visualization:** Renders regional mapping details tailored for planning local Hong Kong weekend getaways.
* **Automated Data Updates:** Features a background data pipeline that automatically refreshes map configurations.
* **Progressive Web App (PWA):** Equipped with service workers and asset manifests for offline viewing support on mobile devices.

---

## 🏗️ Project Architecture

A breakdown of the critical files included in this repository:

```text
weekend/
├── .github/
│   └── workflows/
│       └── update_map.yml    # GitHub Actions workflow for automated map refreshes
├── hk_weekend_map.py         # Core Python script handling geospatial map generation
├── index.html                # Main PWA frontend web view for the map dashboard
├── sw.js                     # Service Worker script managing asset caching and offline status
├── manifest.json             # PWA app configuration, naming, and theme parameters
├── icon-192.png              # Mobile application icon (192x192)
├── icon-512.png              # Mobile application icon (512x512)
└── .nojekyll                 # Bypasses Jekyll processing on GitHub Pages deployments
