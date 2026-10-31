# Character animation assets — 2026-10-28

Generated with image_gen from operator.png and crew.png, then embedded in the Rust application. Transparent PNG, 4 columns × 2 rows. Cell order: waiting, tablet hover, tablet tap, thumbs up, headset, glove adjustment, role work, stopped.

Shared generation prompt:

Create a production sprite animation POSE SHEET, transparent background, landscape canvas with EXACTLY 4 equal-width columns and 2 equal-height rows: 8 separate equal square cells, clean transparent gutters. Each cell is the SAME character waist-up, same scale, head anchor, costume, identity and colors, matching the provided pixel-art reference. Do not draw borders, words, numbers, labels or grid lines. Exactly TWO anatomically coherent arms and hands per character, one per shoulder, no duplicated hands. Each entire pose fits its own cell with 8% margin, never crosses cell boundaries. Keep crisp square pixel art, dark navy, olive, mint cyan, tiny amber highlights. Readable at 200px. CELL ORDER left to right, top row then bottom: (0) neutral waiting, holding equipment; (1) looking down at handheld tablet screen, free index finger hovering above screen; (2) same tablet pose, index finger touching screen in a visible tap; (3) confident small smile or nod with ONE hand thumbs up, other holds equipment; (4) ONE hand touches headset earcup to communicate, other holds tablet lower; (5) calm sideways glance, adjusting opposite glove, equipment safely lowered; (6) ROLE-SPECIFIC WORK POSE described below; (7) STOPPED rest pose, shoulders relaxed, tablet/equipment lowered to waist, hands calm. No salute, no flags, no text.

Role directions: operator keeps opaque cyan visor; mechanic uses the left character in crew.png and turns a wrench on a component in cell 6; naval officer uses the right character and holds binoculars in cell 6, without a duplicate tablet or extra arm.

Alternate sheet edit directions: preserve the entire sheet and grid. Only close the eyes in cell 0 and move the working pose in cell 6: rotate the mechanic's wrench slightly, or turn the officer's binoculars slightly. All other cells remain the same. Transparent background.

Files: operator-poses.png, mechanic-poses.png, officer-poses.png; mechanic-poses-alt.png and officer-poses-alt.png add blink/work variations. No external service is needed at runtime.
