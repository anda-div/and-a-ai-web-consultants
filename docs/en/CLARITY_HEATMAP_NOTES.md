[日本語版（完全版）](../../consultants/03-behavior-heatmap/CLARITY_CAPTURE.md) | **English (summary)**

# Capturing Microsoft Clarity heatmaps without drift

Field notes from monthly client reporting. Every problem below was hit in real
work, and every fix was verified on a live account.

> This is a summary. The full procedure, including the code, lives in the
> [Japanese document](../../consultants/03-behavior-heatmap/CLARITY_CAPTURE.md).
> Scripts: [`clarity_capture_set.py`](../../consultants/03-behavior-heatmap/scripts/clarity_capture_set.py),
> [`clarity_heatmap_capture.py`](../../consultants/03-behavior-heatmap/scripts/clarity_heatmap_capture.py).

## The problem

Clarity draws the heat layer over a **stored screenshot** of the page, chosen by
the tracking code. When the stored screenshot no longer matches the live page,
the colours do not land on the elements they belong to. Clarity's own FAQ is
explicit that you cannot upload or re-capture a screenshot to match a heatmap.

An image where the heat sits next to the button instead of on it is not evidence.
It is worse than no image, because it looks like evidence.

The usual workarounds all fail:

| Approach | What goes wrong |
|---|---|
| Clarity's own download | Heat outside the viewport is not resolved; positions do not line up |
| Full-page screenshot extension | The overlay does not follow; the heat stays fixed while the page moves |
| Mouse-wheel scrolling plus screen capture | Hover tooltips appear in the shot; scroll distance is not consistent |

## What actually works

The heatmap viewport (`#heatmapVisual`) is an **independent scroll container**.
Writing to its `scrollTop` moves the page image and the heat layer **together**.

```js
const c = document.getElementById('heatmapVisual');
c.scrollHeight;      // full page height in CSS px
c.clientHeight;      // one screen
c.scrollTop = 900;   // page and heat move as one
```

So: never touch the mouse. Step `scrollTop` down the page, screenshot each tile,
and stitch. Because you know the exact `scrollTop` of every tile, the join
positions are **computed, not searched for** — no image-difference matching, and
no accumulated error.

One page (desktop and mobile × click and scroll = four images) takes about two
minutes, unattended.

## Things that went wrong, and what they taught us

These are the parts you cannot get from documentation.

### 1. The device parameter is the reverse of what its name suggests

`heatmapDeviceType` does not mean what you would guess. Measured by capturing and
checking the resulting width:

| Value | Rendered width | Actually means |
|---|---|---|
| `0` | 410 px | Mobile |
| `1` | 1413 px | Tablet |
| `2` | 1492 px | Desktop |

The default is `0`. **Ask for desktop, forget the parameter, and you silently get
mobile.** Set `Device` (which sessions to include) and `heatmapDeviceType`
(which width to render at) together, or you filter for phones and render at
desktop width.

### 2. We captured something that was not the heatmap at all

The worst bug we hit. Our fallback logic looked for "a large scrollable div" when
`#heatmapVisual` did not scroll. On a short page, it selected **the click-ranking
panel on the left** — 312 elements, 37,000 px tall — and saved it as the heatmap.

```
Wrong  94 × 33,263 px … the ranking panel
Right 567 ×    962 px … the heatmap
```

**We only noticed because the dimensions were absurd.** With a plausible aspect
ratio, a picture of a completely different UI element would have gone into a
client report.

Two lessons, both now in the procedure: if `#heatmapVisual` exists, never look at
anything else; and **always check the dimensions of what you captured** —
then open at least one image and actually look at it.

### 3. Pages that fit on one screen do not scroll

A login-only page has nothing to scroll. Our code waited for a scrollable
container, never got one, and failed with "heatmap area not found" — on a page
that was working perfectly.

The tell is in the data: scroll depth 5%–95% all showing 100% of visitors, with
zero drop-off. If the container does not scroll, capture it in one piece.

### 4. Click maps and scroll maps came out different widths

We trim the white margins Clarity leaves on either side. Letting each image decide
its own trim produced this:

```
mypage_pc_click.png    567 × 962
mypage_pc_scroll.png  1492 × 962   ← same page, same device
```

Different widths mean different scales, so the two images no longer line up and a
finding that points at "this spot" points at the wrong spot.

The cause: a click map is sparse dots, so many columns look like margin; a scroll
map is a solid band, so almost none do. Measured on raw tiles:

| Page | Click map | Scroll map |
|---|---|---|
| Login-only page (desktop) | 605 px | **1478 px** |
| Same page (mobile) | 366 px | **398 px** |
| Content-heavy pages | identical | identical |

**We first fixed this the wrong way**, by making the scroll map follow the click
map. The widths matched — and both images now had the form fields cut off at the
right edge. The dimensions looked fine. Only opening the image showed it.

The correct rule: take both measurements and **keep the wider one**. Never crop
away a column that either map considers content.

### 5. "Last 30 days" is not a month

The default date range counts back from the day you run it. Run it on 1 September
and you get 2 August – 1 September: **one day of the target month missing, one day
of the next month mixed in.**

We shipped 20 images this way. The output folder was named for the target month;
the contents were not. **A folder name is not evidence that its contents are right.**

Clarity's custom range wants **epoch milliseconds**:

```
?date=Custom&start=1785510000000&end=1788188399000
```

Passing `start=2026-08-01` does not fail loudly — Clarity parses it as a number
and truncates it to `2026`. We found the correct format by setting the range in
the UI and reading the resulting URL, rather than guessing.

A useful check: if this month's images have **exactly** the same dimensions as
last month's, the date range probably did not change.

### 6. "Heatmap area not found" has three different causes

Only one of them is yours to fix.

| Cause | How to tell | What to do |
|---|---|---|
| Session expired | **Pages that worked minutes ago now fail too** | Sign in again (a human has to do this) |
| Rendering not finished | Only tall pages | Increase the settle and timeout values |
| URL match returns nothing | That one page never worked | Change the match operator |

**Run one page that was working a moment ago.** If that fails too, it is the
session, not the page — one run tells you which of the three it is. Retrying the
same failing page tells you nothing. Clarity sessions expire quickly, so test one
page before starting a monthly batch.

### 7. Do not edit a shared script while it is running

The batch script spawns a **separate process per image**. Editing the capture
script mid-run means later images load half-finished code. We lost two images to
`AttributeError: 'tuple' object has no attribute 'name'` while adding a return
value. Captures take minutes. Wait.

## Where this leaves us

Manual capture took roughly ten minutes per page and required someone to watch it.
This takes about two minutes per page, unattended, and does not drift.

It is not zero effort. Very long mobile pages still take time, and Clarity's
session handling needs a human occasionally. But it moved from "a person spends a
morning on it" to "start it and check the output".

We expect Microsoft to fix the underlying screenshot problem eventually. Until
then, these notes are here because we would have wanted them.
