AUTOMATION AGENT — Setup & Run
================================

1) Install dependencies:
   pip install streamlit pandas openpyxl pillow rapidfuzz requests tqdm rawpy imageio --break-system-packages

   (rawpy is only needed if you'll convert .dng RAW images — skip it if you don't need that.)

2) Run the app:
   streamlit run app.py

3) In the browser tab that opens:
   - Type what you want in plain English (e.g. "convert all images in this zip to jpg")
   - Upload the file(s) the task needs (it tells you which ones in the app description)
   - The agent guesses the right tool from your toobox and shows it to you — confirm or
     change it from the dropdown
   - Click Run, then download the result

WHAT'S INSIDE
-------------
All 10 of your original scripts were merged into one app:
  - image link to image.py            -> "Download images from links"
  - Master File.py                    -> "MSL validation"
  - PNG to JPG from ZIP folder.py     -> "PNG to JPG (zip)"
  - All image to jpg.py               -> "Any image to JPG (incl RAW/DNG)"
  - Make images name as parent...py   -> "Rename images by parent folder"
  - ImageName match from excel.py /
    match image name from Excel.py    -> "Match images with excel" (zip + excel, merged)
  - Match shop id from store id.py    -> "Match Shop ID"
  - Match Shop ID From Beat Plan.py   -> "Fuzzy match vs Beat Plan"
  - Master files Updated code.py      -> "Cross-join Shop x SKU"

NOTES
-----
- Since this runs in a browser (Streamlit), folder pickers were replaced with ZIP
  uploads — just zip your image folder before uploading.
- The "intent detection" is simple keyword matching (fast, free, no API needed).
  If you'd rather have it call the real Claude API to read your prompt and pick the
  task, that's an easy swap — happy to wire it up if you want.

LEARNING / MEMORY
------------------
After each run, the agent asks "did it pick the right task?"
  - 👍 Yes  -> it saves a short phrase from your prompt as a new keyword for that task.
  - 👎 No   -> you pick the correct task, and it learns that instead.

These corrections are written to learned_keywords.json (created next to app.py the
first time you give feedback) and are loaded automatically on every future run —
so the agent's matching genuinely improves over time without you editing any code.
Delete learned_keywords.json any time to reset its memory.
