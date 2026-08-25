# Semantic Decomposition of the Mushaf Pages — التفكيك الدلالي لصفحات المصحف

**In one paragraph:** What we did is convert the original page SVG from one big drawing into individual elements, then regroup those elements at the word level (each word tagged surah:ayah:word with its verified text) and at the symbol level — every fatha, kasra, damma, shadda, sukun, dot, madd, waqf sign, and the rest named individually. Nothing is redrawn: the 604 pages stay pixel-identical to the original, but become machine-readable down to the single diacritic, verified at 100% mark coverage and human-reviewed through a dedicated platform.

**في فقرة واحدة:** ما قمنا بعمله هو تحويل ملف الـ SVG الأصلي لكل صفحة من رسمٍ واحد كبير إلى عناصر مستقلة، ثم إعادة تجميع هذه العناصر على مستوى الكلمات (كل كلمة موسومة بسورة:آية:كلمة مع نصّها الموثَّق) وعلى مستوى الرموز — فكل فتحة وكسرة وضمة وشدّة وسكون ونقطة ومدّة وعلامة وقف وغيرها لها اسمها الخاص. لا يُعاد رسم أي شيء: تبقى الصفحات الـ604 مطابقة للأصل بكسلًا بكسل، لكنها تصبح مقروءة آليًا حتى مستوى العلامة الواحدة، بتغطية موثَّقة 100% للعلامات ومراجعةٍ بشرية عبر منصة مخصصة.

---

## English

### What is this?

This project takes the page SVGs of the printed KFGQPC mushaf (in `mushafs/*/svg/`) and gives every piece of ink on every page a **meaning**: which word it belongs to, whether it is a letter body or a mark, and — for marks — exactly which mark it is (fatha, kasra, damma, shadda, sukun, dots, maddah, wasla, dagger-alef, waqf signs, hizb, sajdah…). The original artwork is never redrawn: every output page renders **pixel-identical** to the source.

### Why?

A page image can only be displayed. A decomposed page can be *used*: per-word highlighting for recitation apps, tajweed-aware coloring of individual marks, letter-level analysis, accessibility, search hit highlighting inside the page art itself — the level of the MushafDatabase ligature-based SVG project and beyond, for all 604 pages and multiple qira'at editions.

### How it works (pipeline)

1. **Element splitting** (`tools/split_line_elements.py`) — each page path is split into its connected ink pieces, preserving `evenodd` holes. A pixel verifier proves the split renders identically (~3.58M elements across all editions).
2. **Classification** (`tools/assign_words.py`) — each element becomes a *body* (letter ink) or a *mark*, decided first by its **shape signature** (a scale-free outline fingerprint looked up in a visually-verified table, `.cache/marks/labels.json`, ~3,900 shapes), then by geometry (baseline position, size) for unknown shapes. Guards keep letter twins apart from their mark look-alikes (a dagger-alef vs. a full alef, a sukun ring vs. a final heh).
3. **Word assignment** — the text of each line comes verbatim from the quran.com API (cached, never typed by hand), with **line breaks taken from the QCF v2 page fonts**, which replicate the printed mushaf exactly. A dynamic program splits the line's ink into one cluster per word using letter-level alignment, inter-word gaps, ayah-polygon constraints, and a **width prior from the QCF fonts** (each word's true advance in the page font). Repair passes fix sweeping tails (a qaf bowl under the next word) and trailing-alef ownership.
4. **Mark labeling** — every mark is labeled by its shape signature; welded stacks are split back into single marks; position rules distinguish fatha from kasra; tanween pairs are composed. Each mark carries `data-sig`, so one reviewed decision about a shape applies across the whole mushaf.

### Verification (current status)

- **Marks: 451,994 / 451,994 accounted — 100.0%** across all 604 pages (certified by a clean full sweep; every shape visually verified, including the ornate opening spread of al-Fātiḥah).
- **Word widths agree with the QCF font oracle for ~98.7% of 77,154 words**; the remaining flagged lines are queued for human review.
- Every page is **pixel-identical** to the original artwork.

### Human review

`tools/review_server.py` + `tools/review-platform/` serve a local reviewer platform (`python3 tools/review_server.py --port 8777`):

- **Words step** — hover shows the word; shift-click pieces and click the word they belong to; merge/split/note actions; flagged lines queue.
- **Marks step** — click a mark to label it; mass assignment to identical shapes (mushaf-wide once approved); per-class show/hide.
- **Word audit view** — every word as a card: its real ink above, the matched text below, in reading order; one click flags a mismatch.
- All edits go through an approval queue; approved shape labels merge back via `tools/apply_review_edits.py`.

### Integrity rules

Quranic text is **never typed by hand** — it comes only from verified cached API data. Output pages are verified pixel-identical before acceptance; no ink is ever added, removed, or moved.

---

## العربية

### ما هذا المشروع؟

يأخذ هذا المشروع صفحاتِ مصحف مجمع الملك فهد بصيغة SVG (في `mushafs/*/svg/`) ويمنح كلَّ قطعةِ حبرٍ في كل صفحة **معنىً**: لأي كلمة تنتمي، وهل هي جسم حرف أم علامة، وإن كانت علامةً فما هي تحديدًا (فتحة، كسرة، ضمة، شدّة، سكون، نقاط الإعجام، مدّة، همزة وصل، ألف خنجرية، علامات الوقف، الحزب، السجدة…). لا يُعاد رسم أي شيء: كل صفحة ناتجة تُطابق الأصل **بكسلًا بكسل**.

### لماذا؟

صورة الصفحة تصلح للعرض فقط، أما الصفحة المفكَّكة فيمكن **استعمالها**: تظليل الكلمات للتلاوة والتتبع، تلوين أحكام التجويد على مستوى العلامة الواحدة، التحليل على مستوى الحرف، تحسين الوصول لذوي الاحتياجات، وإبراز نتائج البحث داخل رسم الصفحة نفسه — بمستوى مشروع MushafDatabase وأبعد منه، ولجميع الصفحات الـ604 ولعدة روايات.

### كيف يعمل (خط المعالجة)

1. **تقسيم العناصر** (`tools/split_line_elements.py`) — يُقسَّم رسمُ كل صفحة إلى قطع الحبر المتصلة مع الحفاظ على الفراغات الداخلية، ويُثبت فاحصٌ بكسليٌّ تطابقَ الناتج مع الأصل (نحو 3.58 مليون عنصر).
2. **التصنيف** (`tools/assign_words.py`) — يُصنَّف كل عنصر جسمَ حرفٍ أو علامةً، أولًا عبر **بصمة الشكل** (بصمة محيطية لا تتأثر بالحجم تُقابَل بجدولٍ مُدقَّق بصريًا في `‎.cache/marks/labels.json`، نحو 3900 شكل)، ثم بالهندسة (موضع السطر والحجم) لما لم يُعرف شكله، مع ضوابط تمنع الخلط بين الحرف وشبيهه من العلامات (الألف الخنجرية والألف الكاملة، حلقة السكون وهاء الطرف).
3. **إسناد الكلمات** — نصُّ كل سطر يؤخذ حرفيًا من واجهة quran.com (مخزَّنًا، ولا يُكتب يدويًا أبدًا)، مع أخذ **فواصل الأسطر من خطوط QCF v2** المطابقة للمصحف المطبوع سطرًا بسطر. ثم تُوزَّع قطعُ السطر على الكلمات ببرمجةٍ ديناميكية تعتمد محاذاةَ الحروف، والفراغاتِ بين الكلمات، وحدودَ مضلعات الآيات، و**عروضَ الكلمات الحقيقية من خطوط QCF**. وتُصحِّح ممراتٌ لاحقة الحالاتِ الصعبة (ذيل القاف الممتد تحت الكلمة التالية، وألف الجماعة في نحو آخر الكلمات المنتهية بواو وألف).
4. **تسمية العلامات** — تُسمّى كل علامة ببصمة شكلها، وتُفصَل المجموعات الملتحمة إلى علامات مفردة، وتُميَّز الفتحة من الكسرة بالموضع، ويُركَّب التنوين من قطعه. وتحمل كل علامة `data-sig` بحيث يسري قرارُ مراجعةٍ واحد على المصحف كله.

### التحقق (الحالة الراهنة)

- **العلامات: ‏451,994 / 451,994 موثَّقة — 100.0%** في الصفحات الـ604 كلها (بمسحٍ كامل نظيف، وكل شكلٍ دُقِّق بصريًا، بما فيها صفحتا الافتتاح المزخرفتان).
- **توافق عروض الكلمات مع مرجع خطوط QCF في نحو 98.7% من 77,154 كلمة**، والأسطر المتبقية في قائمة المراجعة البشرية.
- كل صفحة ناتجة **مطابقة بكسليًا** للرسم الأصلي.

### المراجعة البشرية

يوفّر `tools/review_server.py` مع `tools/review-platform/` منصةَ مراجعة محلية (`python3 tools/review_server.py --port 8777`):

- **خطوة الكلمات** — التحويم يُظهر الكلمة؛ اختر القطع بـ Shift ثم انقر الكلمة الصحيحة؛ دمج وفصل وملاحظات؛ قائمة بالأسطر المُعلَّمة.
- **خطوة العلامات** — انقر العلامة لاختيار اسمها؛ إسنادٌ جماعي للأشكال المتطابقة (يسري على المصحف كله بعد الاعتماد)؛ إظهار/إخفاء كل صنف.
- **عرض تدقيق الكلمات** — كل كلمة في بطاقة: حبرُها الحقيقي فوق، والنص المُسنَد تحته، بترتيب القراءة؛ نقرة واحدة تُعلِّم عدم التطابق.
- تمر كل التعديلات بقائمة اعتماد، وتُدمج أسماء الأشكال المعتمدة عبر `tools/apply_review_edits.py`.

### ضوابط الأمانة

نص القرآن **لا يُكتب يدويًا أبدًا** — مصدره حصريًا بياناتٌ موثوقة مخزَّنة من الواجهات المعتمدة. وتُقبل الصفحة الناتجة فقط بعد إثبات تطابقها البكسلي؛ فلا يُضاف حبر ولا يُحذف ولا يُحرَّك.
