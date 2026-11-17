# -*- coding: utf-8 -*-
import zipfile
from xml.etree import ElementTree as ET
from pathlib import Path

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def local(tag):
    return tag.split("}")[-1] if tag else tag


def attrs(el):
    if el is None:
        return ""
    return " ".join(f"{local(k)}={v}" for k, v in el.attrib.items())


def dump(path, out):
    z = zipfile.ZipFile(path)
    print("===", path)
    print("names:", ", ".join(z.namelist()))
    root = ET.fromstring(z.read("word/document.xml"))
    body = root.find(f"{W}body")
    lines = []
    for i, p in enumerate(body.findall(f"{W}p")):
        pPr = p.find(f"{W}pPr")
        style = jc = ind = sp = num = ""
        if pPr is not None:
            ps = pPr.find(f"{W}pStyle")
            if ps is not None:
                style = ps.get(f"{W}val") or ""
            j = pPr.find(f"{W}jc")
            if j is not None:
                jc = j.get(f"{W}val") or ""
            il = pPr.find(f"{W}ind")
            ind = attrs(il)
            spa = pPr.find(f"{W}spacing")
            sp = attrs(spa)
            np = pPr.find(f"{W}numPr")
            if np is not None:
                num = ET.tostring(np, encoding="unicode")
        fonts, sizes, bi = set(), set(), set()
        texts = []
        for r in p.findall(f"{W}r"):
            rPr = r.find(f"{W}rPr")
            if rPr is not None:
                rf = rPr.find(f"{W}rFonts")
                if rf is not None:
                    fonts.add(rf.get(f"{W}ascii") or rf.get(f"{W}hAnsi") or "")
                sz = rPr.find(f"{W}sz")
                if sz is not None:
                    sizes.add(sz.get(f"{W}val"))
                if rPr.find(f"{W}b") is not None:
                    bi.add("b")
                if rPr.find(f"{W}i") is not None:
                    bi.add("i")
            texts.append("".join((t.text or "") for t in r.findall(f"{W}t")))
        text = "".join(texts)
        lines.append(
            f"P{i}|style={style}|jc={jc}|ind={ind}|sp={sp}|fonts={sorted(fonts)}|sz={sorted(sizes)}|bi={sorted(bi)}|{text}"
        )
    Path(out).write_text("\n".join(lines), encoding="utf-8")
    print("paras", len(lines), "wrote", out)
    sect = body.find(f"{W}sectPr")
    if sect is not None:
        print("SECT", ET.tostring(sect, encoding="unicode")[:2500])
    if "word/styles.xml" in z.namelist():
        styles = ET.fromstring(z.read("word/styles.xml"))
        print("--- styles used ---")
        for s in styles.findall(f"{W}style"):
            sid = s.get(f"{W}styleId")
            name_el = s.find(f"{W}name")
            name = name_el.get(f"{W}val") if name_el is not None else ""
            print(sid, "|", name)


dump(
    r"C:\Users\Harmet\Downloads\Курсовой1.ch3.docx",
    r"C:\Users\Harmet\Documents\Default Project\SeatMate\отчёт\_sample_dump.txt",
)
dump(
    r"C:\Users\Harmet\Documents\Default Project\SeatMate\отчёт\Введение.docx",
    r"C:\Users\Harmet\Documents\Default Project\SeatMate\отчёт\_intro_dump.txt",
)
