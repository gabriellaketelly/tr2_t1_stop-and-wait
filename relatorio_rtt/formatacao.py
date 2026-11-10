"""Formatação de texto, tabelas e figuras em LaTeX."""


def escapar_latex(valor):
    substituicoes = {
        "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%",
        "$": r"\$", "#": r"\#", "_": r"\_", "{": r"\{",
        "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
        "α": r"$\alpha$", "β": r"$\beta$", "→": r"$\rightarrow$",
        "≤": r"$\leq$", "≥": r"$\geq$",
    }
    return "".join(substituicoes.get(caractere, caractere) for caractere in str(valor))


def formatar_numero(valor, casas=3):
    if valor is None or valor == "":
        return "N/D"
    try:
        return f"{float(valor):.{casas}f}".replace(".", ",")
    except (ValueError, TypeError):
        return escapar_latex(valor)


def montar_tabela(cabecalhos, linhas, alinhamento=None):
    alinhamento = alinhamento or "l" * len(cabecalhos)
    corpo = [r"\begin{center}\small", r"\begin{tabular}{" + alinhamento + "}",
            r"\toprule", " & ".join(cabecalhos) + r" \\", r"\midrule"]
    corpo += [" & ".join(map(str, linha)) + r" \\" for linha in linhas]
    corpo += [r"\bottomrule", r"\end{tabular}\end{center}"]
    return "\n".join(corpo)


def incluir_figura(caminho, legenda, altura="0.28\\textheight"):
    if not caminho.is_file():
        return r"\begin{quote}\textbf{Pendente:} " + escapar_latex(legenda) + r"\end{quote}"
    caminho_seguro = str(caminho.resolve())
    if any(caractere in caminho_seguro for caractere in "{}%\n"):
        raise ValueError("caminho de figura contém caracteres incompatíveis com LaTeX")
    return (r"\begin{figure}[!ht]\centering" + "\n" +
            r"\includegraphics[width=\linewidth,height=" + altura +
            r",keepaspectratio]{\detokenize{" + caminho_seguro + "}}\n" +
            r"\caption{" + escapar_latex(legenda) + "}\n" + r"\end{figure}")

