"""
Грамматическое согласование прилагательного/причастия с родом существительного.
Портировано из присланного Dm_fraction_2.txt без изменений по существу — это
чистая грамматика, а не игровая механика, инвентить тут нечего.
"""


def inflect_adj(word: str, gender: str) -> str:
    """gender: 'm' (муж.), 'f' (жен.), 'n' (сред.), 'p' (мн.ч.)."""
    if gender == "m":
        return word

    def inflect_single(w: str) -> str:
        is_cap = w[0].isupper() if w else False
        w_low = w.lower()
        res = w_low
        if w_low.endswith("ый") or w_low.endswith("ой"):
            if gender == "f":
                res = w_low[:-2] + "ая"
            elif gender == "n":
                res = w_low[:-2] + "ое"
            elif gender == "p":
                res = w_low[:-2] + "ые"
        elif w_low.endswith("ий"):
            if gender == "p":
                res = w_low[:-2] + "ие"
            else:
                if len(w_low) >= 3 and w_low[-3] in ["ш", "щ", "ж", "ч"]:
                    if gender == "f":
                        res = w_low[:-2] + "ая"
                    elif gender == "n":
                        res = w_low[:-2] + "ее"
                else:
                    if gender == "f":
                        res = w_low[:-2] + "яя"
                    elif gender == "n":
                        res = w_low[:-2] + "ее"
        return res.capitalize() if is_cap else res

    if " " in word:
        return " ".join(inflect_single(p) for p in word.split(" "))
    elif "-" in word:
        return "-".join(inflect_single(p) for p in word.split("-"))
    return inflect_single(word)
