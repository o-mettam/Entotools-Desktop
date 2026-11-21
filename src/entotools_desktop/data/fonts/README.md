# Fonts for PDF labels

`Inter-Regular.ttf`, `Inter-Italic.ttf`, `Inter-Bold.ttf`: static TTFs from the
official Inter 4.1 release, `extras/ttf/` in
https://github.com/rsms/inter/releases/download/v4.1/Inter-4.1.zip
(archive SHA-256 `9883fdd4a49d4fb66bd8177ba6625ef9a64aa45899767dde3d36aa425756b11e`,
downloaded 2026-11-21). SIL Open Font License 1.1 (`LICENSE-Inter.txt`).
ReportLab embeds only the glyphs a PDF uses.

`DejaVuSans.ttf`, `DejaVuSans-Oblique.ttf`: fallback for characters Inter
lacks (notably ♀ ♂). From https://cdn.jsdelivr.net/npm/dejavu-fonts-ttf@2.37.3/ttf/
(sha256 7da195a74c55bef988d0d48f9508bd5d849425c1770dba5d7bfc6ce9ed848954 and
4af75fa16ee6d3ad43e1ecec41862c24954af26a55c6bb1ebb27bd486a50f5f4). Bitstream Vera /
DejaVu license (`LICENSE-DejaVu.txt`).
