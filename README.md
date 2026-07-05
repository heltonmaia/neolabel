# NeoLabel

**Video-based pose annotation, built for research.**

Label video frames, assign work to annotators, and export ready-to-train
datasets. Two keypoint schemas ship by default: **17-point infant pose
(COCO)** and **7-point rodent pose** for behavioral assays such as
**Open Field (OF)** and **Elevated Plus Maze (EPM)**.

<p align="center">
  <img src="docs/screenshots/login.png" alt="NeoLabel sign-in screen showing the project tagline and the two default keypoint schemas (Infant 17-pt and Rodent 7-pt)" width="820">
  <br>
  <sub><em>Sign-in screen — the two default schemas and the supported workflow are surfaced right at the entry point. (Predates the Google Sign-In rollout: the password form shown here has since been replaced by a one-time email code sent to a single configured admin address, at the "/emergency" page — the primary control is a Google button. See "Run it" below.)</em></sub>
</p>

> Full specification (domain model, API reference, roadmap) lives in
> **[SPEC.md](./SPEC.md)**.

## What you can do

NeoLabel covers the path from raw video to a trainable dataset in four
steps:

1. **Upload videos** at a chosen FPS — FFmpeg extracts the frames — or
   **upload a ZIP of images** to import each one as a frame. Either way,
   optionally resize to **640×640** (letterbox or stretch). You can also
   **import an existing COCO keypoints dataset** to start from
   pre-annotated items.
2. **Assign work** — admins assign whole videos to a specific annotator
   or leave them in the admin pool. Per-user visibility is enforced;
   annotators only see what's assigned to them.
3. **Annotate** with mouse or full-keyboard workflow; auto-save on every
   action; undo history of 50 steps.
4. **Export** as JSON / JSONL / CSV, YOLO-pose ZIP
   (Ultralytics-ready, COCO 17 keypoints), or a full-bundle ZIP that
   includes every referenced frame for portability.

<p align="center">
  <img src="docs/screenshots/video-upload.png" alt="Admin view of a project showing the Upload video form (FPS slider, assignee dropdown, resize policy), and collapsed sections for COCO import, Videos, and Items" width="820">
  <br>
  <sub><em>Admin view of a project — upload videos, choose extraction FPS and resize policy, optionally assign to a user. The same screen also lets admins import an existing COCO keypoints dataset (e.g. a Roboflow export) as pre-annotated items.</em></sub>
</p>

## What gets annotated

Two ship-ready schemas, with room for new ones as needs arise:

- **Infant pose** — 17 COCO keypoints, with an interactive baby avatar
  on the right panel as a visual guide.
- **Rodent pose** — 7 keypoints (`N` nose, `LEar` / `REar` ears, `BC`
  body center, `TB` / `TM` / `TT` tail base / middle / tip), tailored
  for behavioral assays.

<p align="center">
  <img src="docs/schemas/rodent-pose.svg" alt="Rodent pose — 7 keypoints (N, LEar, REar, BC, TB, TM, TT)" width="280">
  <br>
  <sub><em>Rodent keypoint schema currently in use.</em></sub>
</p>

## How annotation works

Each extracted frame becomes an **item** you walk through with keyboard
shortcuts. The right panel shows a live avatar of where you are in the
schema, the chosen traversal order, and the action buttons.

<p align="center">
  <img src="docs/screenshots/pose-annotate.png" alt="Pose annotation UI showing a sample infant frame with all 17 keypoints placed (numbered green dots) on the left, and the keypoint avatar plus action buttons on the right" width="820">
  <br>
  <sub><em>Pose annotation UI. <strong>The frame above is AI-generated for documentation purposes — not a real subject.</strong> Using synthetic frames in public materials is the recommended way to demo annotation tools that target sensitive populations (infants, patients), since you keep informed-consent obligations clean while still showing the product accurately.</em></sub>
</p>

Key interactions:

- **Mouse or keyboard.** Arrows + Enter/Space to place a point;
  clicking directly on the image always overrides the pointer.
- **Shortcuts.** `Tab` / `N` next keypoint, `1`–`9` jump, `O` occluded,
  `X` out of frame (saved as COCO `v=0`), `U` undo, `[` / `]` previous
  / next item.
- **Traversal order.** Top-to-bottom (default), left-contour, or
  right-contour. Output array order is unchanged across modes — only
  the pointer behavior changes.
- **Reuse previous frame as template.** Optional toggle that prefills
  a new frame with the previous frame's keypoints, so you only drag
  to adjust. Safe to turn on/off mid-session.
- **Auto-save** on every action; **undo history** of 50 steps;
  per-point and clear-all reset.
- **Review states.** Items move through `pending → in-progress →
  reviewed`; reviewers can approve or send back.

## Roles

- **admin** — uploads videos, imports COCO datasets, assigns
  annotators, deletes projects and items. Destructive bulk operations
  are admin-only.
- **annotator** — sees and works on items assigned to them.
- **reviewer** — approves or sends back annotated items.

## Export

For pose projects:

| Format            | Includes pending? | Best for                                                                 |
| ----------------- | ----------------- | ------------------------------------------------------------------------ |
| JSON / JSONL / CSV | Yes (pending rows carry `annotation: null`) | Inspection, scripting, custom pipelines                  |
| YOLO-pose ZIP     | Annotated only   | Direct training with Ultralytics (COCO 17 keypoints)                     |
| Full bundle ZIP   | All items + every referenced source frame | Portable archive across machines, reproducibility       |

Downloads are streamed with a progress bar and are cancellable.

## Run it

The recommended path is **Docker** — bundles FFmpeg, pins Python/Node
versions, and mounts source code for hot-reload.

Sign-in is **Google Sign-In** for everyone, restricted to an email
allowlist, plus **emergency email-code access** for one configured
admin address, for when Google/OAuth is unavailable or misconfigured.

```bash
cp .env.example .env
cp allowlist.example.json allowlist.json
# edit allowlist.json: the emails allowed to sign in, and their role
# edit .env: GOOGLE_CLIENT_ID + VITE_GOOGLE_CLIENT_ID (a Google OAuth
# Web Client ID — no client secret needed), and RESEND_API_KEY /
# EMAIL_FROM / EMERGENCY_ADMIN_EMAIL for the emergency access code
docker compose up --build -d
```

Then open <http://localhost:5173>. The API and its OpenAPI docs are at
<http://localhost:8000/docs>.

`allowlist.json` (a list of `{email, role, name}`) is read fresh on
every Google sign-in, and also at backend startup:

- Any listed email can sign in with Google; a matching user is
  provisioned on first login (or pre-provisioned at startup, so an
  admin can assign work to them before that first login).
- Removing an email denies it on the very next sign-in attempt — no
  restart needed. To also prune that user's now-stale record, use the
  reconciliation script (see SPEC).

Without `GOOGLE_CLIENT_ID` set, Google Sign-In is not configured and
only emergency access works — go directly to `/emergency`, request a
one-time code, and sign in as `EMERGENCY_ADMIN_EMAIL`.

For a native (non-Docker) setup, see [SPEC.md](./SPEC.md). Requires
Python 3.12, Node 18+, and FFmpeg on `PATH`.

## Data

All runtime data lives under `./data/` (configurable via `DATA_DIR`).
Each project is a subfolder with its config, items, annotations,
uploaded videos, and extracted frames. **No database** — backup is just
copying that folder.

## Cite

If you use NeoLabel in academic work, please cite it. The "Cite this
repository" button on the GitHub page reads
[CITATION.cff](./CITATION.cff) and also offers an APA-style entry.
For BibTeX, copy the block below:

```bibtex
@software{maia_neolabel_2026,
  author  = {Maia, Helton and Tavares Filho, Marcos Aur{\'e}lio},
  title   = {{NeoLabel}: Video-based pose annotation for research},
  year    = {2026},
  version = {0.1.0},
  url     = {https://github.com/neolabel/app},
  license = {Apache-2.0}
}
```

## License

**[Apache License 2.0](./LICENSE)** — permissive open-source license,
allows both commercial and non-commercial use, with attribution.

Copyright (c) 2026 The NeoLabel authors

When redistributing: keep `LICENSE` and `NOTICE`, preserve copyright /
patent / trademark / attribution notices, and mark any modified files
as changed. Full terms:
[apache.org/licenses/LICENSE-2.0](https://www.apache.org/licenses/LICENSE-2.0).

## Authors

- **Helton Maia** — <helton.maia@ufrn.br> —
  [heltonmaia.com](https://heltonmaia.com)
- **Marcos Aurélio Tavares Filho**
