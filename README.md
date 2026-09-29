# yotamvaknin.github.io

Personal website of Yotam Vaknin.

- `index.html` — landing page (bio, CV, publications, photography)
- `assets/` — portrait and web-sized photos (`photos/thumb` for the grid, `photos/full` for the lightbox)
- `blog/` — the Hebrew physics blog (static export of the old Gatsby site)
- `Friction/`, `QFT-part-*/`, `QM-part-*/` — redirects from the old blog URLs to `/blog/...`
- `sw.js` — unregisters the old Gatsby offline service worker

## Adding photos

Put new JPEGs in `../Photos/general_photography/` and run:

    python3 add_photos.py

It strips metadata (location, camera info) losslessly, makes thumbnails, updates the gallery in `index.html`, then commits and pushes. Use `--no-push` to preview locally first, or pass specific files/folders as arguments.
