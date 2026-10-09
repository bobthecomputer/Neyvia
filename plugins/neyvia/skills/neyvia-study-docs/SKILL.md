---
name: neyvia-study-docs
description: "Use when writing or editing a study document on Paul's neyvia-study template (a course or a formula & method sheet in LaTeX), or when turning notes into one."
---

Paul's study documents use one fixed shape per concept. Write content only; the
class (`templates/latex/neyvia-study/neyvia-study.cls`) does the look. Build and
check with the `documents` manual (`manuals/cl/documents.cl`): `documents.create`,
`documents.build`, `documents.check`, `documents.render`.

## Shape

```latex
\documentclass[course]{neyvia-study}   % or [sheet]: keeps blocks 1-3 only
\studytitle{Linear Algebra}
\begin{document}
\maketitle
\studychapter{Sets and maps}
\studypart{I}{Sets}
\begin{concept}{Surjective maps}{p1 col2}      % title, source tag
\begin{definition} ... \end{definition}         % 1 the statement, exact
\begin{method}{Prove that $f$ is surjective}    % 2 the written proof
\step{Let $y\in F$.}
\step{We look for $x\in E$ such that $f(x)=y$.}
\step{$\therefore f$ is surjective.}
\end{method}
\begin{reflex} Surjective \ra{} start with $y\in F$. \end{reflex}   % 3
\begin{worked}{...} ... \result{...} \end{worked}                   % 4
\begin{traps} \trap{...} \end{traps}                                % 5 optional
\begin{practice} \try{...} \answer{...} \end{practice}              % 6 optional
\end{concept}
\end{document}
```

## Writing rules

- **One transformation per line.** Each `\step` changes one thing; copy the
  previous expression and change only that. A long chain is several steps.
- **The method is the actual proof** you would write on paper, opening with its
  keyword: Let, Assume, Take, We look for, Check, Then; closing with `$\therefore$`.
- **A reflex is a single cue:** `trigger \ra{} first move`. One line, no
  explanation, nothing a student has to unpack.
- **Traps only when useful:** a real mistake people make, said plainly. No
  traps block is better than a filler one.
- **Practice is a tiny changed example:** the worked example with one number,
  set or function changed, then its answer. Never a new topic.
- **Plain wording.** Short sentences, everyday words, no "it is easy to see".
- **Mark through the macros, never by hand.** Quantifiers: `\forall`, `\exists`,
  `\exists!` (or `\ALL`, `\EX`, `\EXU`) colour themselves. Proof keywords: a
  `\step` that starts with one is coloured; elsewhere use `\kw{Hence}`. Never
  `\textcolor` or `\textbf` a keyword yourself.
- **Every concept has a source tag** (page and column of the handout), and its
  blocks stay in order 1 to 6.
- Use `\dline{...}` for a displayed formula in a definition, `\result{...}` for
  the boxed answer, `\studynote{...}` for a remark about the source.

## Done means

`documents.check` passes (compiles, no undefined references, no overfull box
over 1 pt, Inter embedded, blocks in order with tags, page count in limits) and
you have looked at the pages from `documents.render`.
