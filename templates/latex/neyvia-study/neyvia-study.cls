%% neyvia-study.cls -- Paul's study-document style for Neyvia.
%%
%% Two variants of one look:
%%   \documentclass[course]{neyvia-study}  full course: cover legend, contents,
%%                                          every concept in six labelled blocks
%%   \documentclass[sheet]{neyvia-study}   compact formula & method sheet: one
%%                                          framed card per concept with the
%%                                          formula, method skeletons and reflex
%%
%% A concept is always the same six-part structure:
%%   1 definition / formula (red)   2 method (blue)     3 reflex (green)
%%   4 worked example (grey)        5 traps (orange)    6 practice (purple)
%% The sheet variant keeps 1-3 and drops 4-6, so one source can feed both.
%%
%% Options: course | sheet, autoquant | noautoquant, autokw | noautokw
%% Build:   python scripts/study_docs.py build file.tex   (Tectonic, XeTeX)
%% Fonts:   Inter 4.0 (SIL OFL 1.1, fonts/LICENSE.txt) next to this class,
%%          Computer Modern for maths, Latin Modern Sans for block labels.
\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{neyvia-study}[2026/10/06 v1.0 Neyvia study documents]

\newif\ifnstudy@sheet \nstudy@sheetfalse
\newif\ifnstudy@autoquant \nstudy@autoquanttrue
\newif\ifnstudy@autokw \nstudy@autokwtrue
\DeclareOption{course}{\nstudy@sheetfalse}
\DeclareOption{sheet}{\nstudy@sheettrue}
\DeclareOption{autoquant}{\nstudy@autoquanttrue}
\DeclareOption{noautoquant}{\nstudy@autoquantfalse}
\DeclareOption{autokw}{\nstudy@autokwtrue}
\DeclareOption{noautokw}{\nstudy@autokwfalse}
\DeclareOption*{\PassOptionsToClass{\CurrentOption}{article}}
\ProcessOptions\relax
\LoadClass[10pt,a4paper]{article}

%% ---------------------------------------------------------------- packages
\ifnstudy@sheet
  \RequirePackage[a4paper,top=17mm,bottom=16mm,left=16mm,right=16mm]{geometry}
\else
  \RequirePackage[a4paper,top=22mm,bottom=20mm,left=19mm,right=19mm]{geometry}
\fi
\RequirePackage{fontspec}
\RequirePackage{amsmath,amssymb,mathtools,amsfonts}
\RequirePackage{xcolor}
\RequirePackage[most]{tcolorbox}
\RequirePackage{enumitem,fancyhdr,multicol,needspace,etoolbox}
\RequirePackage[hidelinks,bookmarksnumbered]{hyperref}

%% ---------------------------------------------------------------- fonts
%% Inter is loaded by file name from the template's fonts/ folder (the build
%% puts that folder on Tectonic's search path). \studyfontpath{dir/} points
%% fontspec at another folder; a system-installed Inter is the fallback.
\def\nstudy@fontpath{}
\providecommand\studyfontpath[1]{\def\nstudy@fontpath{#1}}
\IfFontExistsTF{\nstudy@fontpath Inter-Regular.otf}{%
  \setmainfont{Inter}[Path=\nstudy@fontpath, Extension=.otf,
    UprightFont=*-Regular, ItalicFont=*-Italic,
    BoldFont=*-ExtraBold, BoldItalicFont=*-ExtraBoldItalic, Ligatures=TeX]}{%
  \setmainfont{Inter}[Ligatures=TeX]}

%% ---------------------------------------------------------------- colours
\definecolor{quant}{HTML}{0E7490}
\definecolor{kwc}{HTML}{1D4ED8}
\definecolor{defc}{HTML}{B42318}
\definecolor{methc}{HTML}{1D4ED8}
\definecolor{reflc}{HTML}{15803D}
\definecolor{examc}{HTML}{475569}
\definecolor{trapc}{HTML}{C2410C}
\definecolor{pracc}{HTML}{6D28D9}
\definecolor{ink}{HTML}{1F2937}
\definecolor{mute}{HTML}{6B7280}
\definecolor{boxc}{HTML}{94A3B8}\definecolor{boxbg}{HTML}{F8FAFC}

%% ---------------------------------------------------------------- contents
\renewcommand*\l@section[2]{\addpenalty{-300}\vskip 7pt plus 1pt\noindent{\bfseries\color{defc}#1}\hfill{\bfseries #2}\par}
\renewcommand*\l@subsection[2]{\addpenalty{-50}\vskip 2pt\noindent\hspace*{0.6em}{\bfseries\color{methc}#1}\hfill\color{mute}#2\par}
\renewcommand*\l@subsubsection{\@dottedtocline{3}{1.4em}{2.8em}}
\renewcommand\@dotsep{2.2}
\setcounter{tocdepth}{3}

%% ---------------------------------------------------------------- page
\hyphenpenalty=10000 \exhyphenpenalty=10000 \tolerance=2000 \emergencystretch=3em
\raggedright
\setlength{\parindent}{0pt}
\newlength{\mind}\setlength{\mind}{1.25em}
\setlength{\parskip}{3pt}
\ifnstudy@sheet
  \linespread{1.15}\setlength{\columnsep}{6mm}\setlength{\columnseprule}{0.2pt}\setlength{\mind}{1.05em}
\else
  \linespread{1.22}
\fi

%% ---------------------------------------------------------------- marking
%% Proof keywords are bold blue; quantifiers are bold teal.
\newcommand{\kw}[1]{\textcolor{kwc}{\textbf{#1}}}
\let\plainforall\forall
\let\plainexists\exists
\newcommand{\ALL}{{\color{quant}\boldsymbol{\plainforall}}\,}
\newcommand{\EX}{{\color{quant}\boldsymbol{\plainexists}}\,}
\newcommand{\EXU}{{\color{quant}\boldsymbol{\plainexists!}}\,}
\ifnstudy@autoquant
  %% \forall, \exists and \exists! colour themselves, exactly like \ALL, \EX, \EXU.
  %% \plainforall and \plainexists stay available for a symbol that is only named.
  \AtBeginDocument{%
    \renewcommand{\forall}{\ALL}%
    \renewcommand{\exists}{\@ifnextchar!{\nstudy@existsone}{\EX}}}
  \def\nstudy@existsone!{\EXU}
\fi
%% \ra: the arrow of a reflex cue (cue \ra{} action).
\newcommand{\ra}{\ensuremath{\rightarrow}}

%% Keywords that colour themselves when a \step starts with them.
\ExplSyntaxOn
\regex_const:Nn \c__nstudy_keyword_regex
  { \A ( We\ look\ for | We\ show | Assume\ by\ contradiction | Base\ case | Induction\ step
       | For\ all | For\ each | There\ exists | There\ exist
       | Let | Assume | Then | Take | Check | Hence | Since | So | Thus | Compute | Solve
       | Write | Case | Conversely | Show | Fix | Choose | Define | Denote | Put | Set
       | Apply | Find | Recall | Moreover | Indeed | Otherwise | Suppose | Claim | Conclude )
    ( [\ .,:;] | \Z ) }
\tl_new:N \l__nstudy_step_tl
\bool_new:N \g__nstudy_autokw_bool
\cs_new_protected:Npn \__nstudy_mark_keyword:n #1
  {
    \tl_set:Nn \l__nstudy_step_tl {#1}
    \regex_replace_once:NnN \c__nstudy_keyword_regex { \c{kw}\cB\{ \1 \cE\} \2 } \l__nstudy_step_tl
    \tl_use:N \l__nstudy_step_tl
  }
\NewDocumentCommand \nstudyautokw { m }
  { \bool_if:NTF \g__nstudy_autokw_bool { \__nstudy_mark_keyword:n {#1} } {#1} }
\NewDocumentCommand \studyautokeywords { m }
  { \str_if_eq:nnTF {#1} {on} { \bool_gset_true:N \g__nstudy_autokw_bool } { \bool_gset_false:N \g__nstudy_autokw_bool } }
\tl_new:N \l__nstudy_trim_tl
\NewDocumentCommand \nstudytrim { +m }
  { \tl_set:Nn \l__nstudy_trim_tl {#1} \tl_trim_spaces:N \l__nstudy_trim_tl \tl_use:N \l__nstudy_trim_tl }
\ExplSyntaxOff
\ifnstudy@autokw\studyautokeywords{on}\else\studyautokeywords{off}\fi

%% ---------------------------------------------------------------- maths helpers
\newcommand{\F}{\mathbb{F}}
\newcommand{\R}{\mathbb{R}}
\newcommand{\C}{\mathbb{C}}
\newcommand{\N}{\mathbb{N}}
\newcommand{\Z}{\mathbb{Z}}
\newcommand{\Q}{\mathbb{Q}}
\newcommand{\Id}{\mathrm{Id}}
\newcommand{\Mat}{\operatorname{Mat}}
\newcommand{\GL}{\mathrm{GL}}
\newcommand{\End}{\operatorname{End}}
\newcommand{\Lin}{\mathcal{L}\mathrm{in}}
\newcommand{\rk}{\operatorname{rk}}
\newcommand{\tr}{\operatorname{tr}}
\newcommand{\spec}{\operatorname{sp}}
\newcommand{\im}{\operatorname{im}}
\newcommand{\Span}{\operatorname{span}}
\newcommand{\diag}{\operatorname{diag}}
\newcommand{\Diag}{\operatorname{Diag}}
\newcommand{\eps}{\varepsilon}
\newcommand{\Sn}{\mathfrak{S}_n}
\newcommand{\Sk}{\mathfrak{S}_k}
\newcommand{\card}{\#}
\newcommand{\lb}{[\![\,}
\newcommand{\rb}{\,]\!]}
\newcommand{\ii}[2]{[\![\,#1\,;\,#2\,]\!]}
\newcommand{\tp}{\mathsf{T}}
\newcommand{\adj}{{*}}
\newcommand{\abs}[1]{\left|#1\right|}
\newcommand{\norm}[1]{\left\|#1\right\|}
\newcommand{\nnorm}[1]{\left|\!\left|\!\left|#1\right|\!\right|\!\right|}
\newcommand{\set}[1]{\left\{#1\right\}}
\newcommand{\ang}[2]{\left\langle #1\,\middle|\,#2\right\rangle}
\newcommand{\why}[1]{\quad\text{\color{mute}\small(#1)}}
\newcommand{\sgn}{\operatorname{sign}}
\newcommand{\Her}{\mathrm{H}}
\newcommand{\Sym}{\mathrm{S}}
\newcommand{\Un}{\mathrm{U}}
\newcommand{\On}{\mathrm{O}}
\newcommand{\cE}{\mathcal{E}}

%% ---------------------------------------------------------------- lines
%% \mline{indent}{text}: one transformation per line, hanging indent.
\newcommand{\mline}[2]{\par\noindent\hspace*{#1}\hangindent=\dimexpr#1+1.6em\relax\hangafter=1 #2}
%% \step{...} one line of a method or worked example; \step[n]{...} indents n
%% levels. A leading proof keyword (Let, Assume, Then, ...) is coloured.
%% \step*{...} never colours.
\NewDocumentCommand\step{s O{0} m}{\mline{#2\mind}{\IfBooleanTF{#1}{#3}{\nstudyautokw{#3}}}}
%% \dline{maths}: one displayed formula line inside a definition.
\newcommand{\dline}[1]{\par\vspace{1pt}\noindent$\displaystyle #1$\par\vspace{1pt}}
%% \result{maths}: the boxed final line of a worked example.
\newcommand{\resultbox}[1]{\fcolorbox{boxc}{boxbg}{\vphantom{Ag}$\displaystyle #1$}}
\newcommand{\result}[1]{\mline{0pt}{\resultbox{#1}}}
%% \point{text}: a bulleted line inside a definition.
\newcommand{\point}[1]{\par\noindent\hangindent=1.2em\hangafter=1\hspace*{0.4em}\textbullet\ #1}
%% \trap{text}: one bullet in a traps block.
\newcommand{\trap}[1]{\mline{0pt}{\textbullet\ #1}}
%% \try{question} and \answer{answer}: the practice pair.
\newcommand{\studytrylabel}{Try:}
\newcommand{\studyanswerlabel}{Answer:}
\newcommand{\try}[1]{\mline{0pt}{\textbf{\studytrylabel} #1}}
\newcommand{\answer}[1]{\mline{0pt}{\textcolor{mute}{\textbf{\studyanswerlabel} #1}}}

%% ---------------------------------------------------------------- labels
\newcommand{\studylabeldefinition}{DEFINITION / FORMULA}
\newcommand{\studylabelmethod}{METHOD}
\newcommand{\studylabelreflex}{WHAT TO THINK / REFLEX}
\newcommand{\studylabelworked}{WORKED EXAMPLE}
\newcommand{\studylabeltraps}{TRAPS / SHORTCUTS}
\newcommand{\studylabelpractice}{TINY CHANGED EXAMPLE / PRACTICE}
\newcommand{\studysheetlabelmethod}{METHOD}
\newcommand{\studysheetlabelreflex}{REFLEX}
%% \studytag{colour}{number}{text}: the small coloured label of a block.
\newcommand{\studytag}[3]{\fcolorbox{#1}{#1!9}{\textcolor{#1}{\sffamily\bfseries\scriptsize\ #2\,\,#3\ }}}
\newcommand{\nstudy@label}[3]{\par\vspace{5pt}\Needspace{4\baselineskip}\noindent\setlength{\fboxsep}{2.2pt}\setlength{\fboxrule}{0.7pt}\studytag{#1}{#2}{#3}}
\newcommand{\nstudy@caption}[1]{\ \ \textcolor{mute}{\small #1}}
\newcommand{\nstudy@afterlabel}{\par\nopagebreak\vspace{3pt}}

%% ---------------------------------------------------------------- text
\newcommand{\studytitle}[1]{\def\nstudy@title{#1}}
\newcommand{\studysubtitle}[1]{\def\nstudy@subtitle{#1}}
\newcommand{\studytagline}[1]{\def\nstudy@tagline{#1}}
\newcommand{\studyrunning}[1]{\def\nstudy@running{#1}}
\newcommand{\studysubject}[1]{\def\nstudy@subject{#1}}
\newcommand{\studysourceprefix}[1]{\def\nstudy@srcprefix{#1}}
\newcommand{\studynotelabel}[1]{\def\nstudy@notelabel{#1}}
\studytitle{Study notes}
\ifnstudy@sheet
  \studysubtitle{Formula \& Method Sheet}
  \studytagline{Formula $\to$ method skeleton \ → \ reflex. Quantifiers in colour: $\ALL\ \EX\ \EXU$.}
\else
  \studysubtitle{Complete Course}
  \studytagline{}
\fi
\def\nstudy@running{\nstudy@title\ --- \nstudy@subtitle}
\studysubject{}
\studysourceprefix{}
\studynotelabel{Note:}
\AtBeginDocument{\hypersetup{pdftitle={\nstudy@title\ --- \nstudy@subtitle},pdfauthor={},pdfsubject={\nstudy@subject}}}

%% ---------------------------------------------------------------- running heads
\pagestyle{fancy}\fancyhf{}
\ifnstudy@sheet
  \renewcommand{\headrulewidth}{0pt}
  \fancyhead[L]{\scriptsize\textcolor{mute}{\nstudy@running}}\fancyhead[R]{\scriptsize\textcolor{mute}{\leftmark}}\fancyfoot[C]{\scriptsize\textcolor{mute}{\thepage}}
\else
  \renewcommand{\headrulewidth}{0.3pt}
  \fancyhead[L]{\small\textcolor{mute}{\nstudy@running}}\fancyhead[R]{\small\textcolor{mute}{\leftmark}}\fancyfoot[C]{\small\textcolor{mute}{\thepage}}
\fi

%% ---------------------------------------------------------------- cover
%% The legend explains the six blocks; \studylegend can be used on its own.
\newcommand{\studylegendtitle}{How every concept is laid out}
\newcommand{\studylegend}{%
\begin{tcolorbox}[enhanced,before upper={\raggedright},frame hidden,colback=black!3,boxrule=0pt,arc=3pt,left=10pt,right=10pt,top=8pt,bottom=8pt,before skip=9.26pt]
\small\textbf{\studylegendtitle}\par\vspace{4pt}
\studytag{defc}{1}{DEFINITION / FORMULA}\ \ the statement, exact\par\vspace{3pt}
\studytag{methc}{2}{METHOD}\ \ the actual mathematical writing: \kw{Let}, \kw{Assume}, $\ALL$, $\EX$, conclusion\par\vspace{3pt}
\studytag{reflc}{3}{REFLEX}\ \ one cue to fire without thinking\par\vspace{3pt}
\studytag{examc}{4}{WORKED EXAMPLE}\ \ one transformation per line\par\vspace{3pt}
\studytag{trapc}{5}{TRAPS}\ \ only when useful\par\vspace{3pt}
\studytag{pracc}{6}{PRACTICE}\ \ a tiny changed example\par\vspace{6pt}
Quantifiers appear in colour: $\ALL x\in E,\ \EX y\in F,\ \EXU z$. Keywords of a proof appear as \kw{Let}, \kw{Assume}, \kw{Then}.
\end{tcolorbox}}
\newcommand{\makestudycover}{%
\ifnstudy@sheet
  \thispagestyle{empty}
  {\noindent\fontsize{26}{30}\selectfont\bfseries \nstudy@title\par}{\noindent\Large \nstudy@subtitle\par}
  \vspace{2pt}{\small\textcolor{mute}{\nstudy@tagline}}\par\vspace{2pt}
  {\small\setlength{\parskip}{0pt}\setcounter{tocdepth}{2}\tableofcontents}
  \clearpage
\else
  \thispagestyle{empty}
  \vspace*{38mm}
  {\fontsize{34}{40}\selectfont\bfseries \nstudy@title\par}
  \vspace{4pt}{\LARGE \nstudy@subtitle\par}
  \ifx\nstudy@tagline\@empty\else\vspace{10pt}{\large\color{mute}\nstudy@tagline\par}\fi
  \vspace{16mm}
  \studylegend
  \newpage
  \tableofcontents
  \newpage
\fi}
\let\maketitle\makestudycover

%% ---------------------------------------------------------------- structure
%% \studychapter[label]{title}   \studypart{label}{title}
%% \begin{concept}[number]{title}{source tag} ... \end{concept}
\newcounter{studychapter}
\newcounter{concept}[studychapter]
\newcommand{\nstudy@chapterlabel}{}
\NewDocumentCommand\studychapter{o m}{%
  \stepcounter{studychapter}%
  \IfNoValueTF{#1}{\edef\nstudy@chapterlabel{\arabic{studychapter}}}{\def\nstudy@chapterlabel{#1}}%
  \ifnstudy@sheet
    \markboth{Chapter \nstudy@chapterlabel}{Chapter \nstudy@chapterlabel}\phantomsection\addcontentsline{toc}{section}{Chapter \nstudy@chapterlabel\ ·\ #2}
    \par\Needspace{6\baselineskip}{\noindent\Large\bfseries\textcolor{defc}{Chapter \nstudy@chapterlabel}\ \ #2\par}{\color{defc}\hrule height 0.8pt}\vspace{3pt}
  \else
    \clearpage\markboth{Chapter \nstudy@chapterlabel}{Chapter \nstudy@chapterlabel}
    \phantomsection\addcontentsline{toc}{section}{Chapter \nstudy@chapterlabel\ ·\ #2}
    {\noindent\fontsize{22}{26}\selectfont\bfseries\textcolor{defc}{Chapter \nstudy@chapterlabel}\par}\vspace{2pt}{\noindent\LARGE\bfseries #2\par}\vspace{3pt}{\color{defc}\hrule height 1pt}\vspace{6pt}
  \fi}
\newcommand{\studypart}[2]{%
  \ifnstudy@sheet
    \par\Needspace{10\baselineskip}\phantomsection\addcontentsline{toc}{subsection}{#1\ \ #2}{\bfseries\textcolor{methc}{#1\ \ #2}\par}\vspace{2pt}
  \else
    \par\vspace{8pt}\Needspace{12\baselineskip}\phantomsection\addcontentsline{toc}{subsection}{#1\ \ #2}{\noindent\Large\bfseries\textcolor{methc}{#1}\ \ #2\par}\vspace{1pt}{\color{methc!40}\hrule height 0.6pt}
  \fi}
%% Each concept records its number, source tag and block order in the .aux
%% file; the outcome checks read them back (see manuals/cl/documents.cl).
\newcommand{\nstudy@concept}{}
\newcommand{\nstudy@blocks}{}
\newcommand{\nstudy@record}[1]{\ifx\nstudy@concept\@empty\else\xdef\nstudy@blocks{\nstudy@blocks#1}\fi}
\newcommand{\nstudy@writeconcept}[2]{\immediate\write\@auxout{\string\nstudyconcept{#1}{\nstudy@blocks}{\expandafter\detokenize\expandafter{#2}}}}
\providecommand\nstudyconcept[3]{}
\AtBeginDocument{\immediate\write\@auxout{\string\providecommand\string\nstudyconcept[3]{}}}
\ifnstudy@sheet
  \NewDocumentEnvironment{concept}{o m m}{%
    \stepcounter{concept}%
    \IfNoValueTF{#1}{\edef\nstudy@concept{\nstudy@chapterlabel.\arabic{concept}}}{\def\nstudy@concept{#1}}%
    \gdef\nstudy@blocks{}\def\nstudy@tag{#3}%
    \begin{tcolorbox}[enhanced,before upper={\raggedright},colback=white,colframe=black!18,boxrule=0.4pt,arc=1.5pt,left=6pt,right=6pt,top=3pt,bottom=3pt,before skip=5pt,after skip=5pt,nobeforeafter,breakable=false]
    {\bfseries\normalsize\textcolor{defc}{\nstudy@concept}\ \ #2}\hfill{\footnotesize\textcolor{mute}{\nstudy@srcprefix#3}}\par\vspace{1pt}}
    {\end{tcolorbox}\nstudy@writeconcept{\nstudy@concept}{\nstudy@tag}\gdef\nstudy@concept{}}
\else
  \NewDocumentEnvironment{concept}{o m m}{%
    \stepcounter{concept}%
    \IfNoValueTF{#1}{\edef\nstudy@concept{\nstudy@chapterlabel.\arabic{concept}}}{\def\nstudy@concept{#1}}%
    \gdef\nstudy@blocks{}\def\nstudy@tag{#3}%
    \par\vspace{10pt}\Needspace{9\baselineskip}\phantomsection\addcontentsline{toc}{subsubsection}{\protect\numberline{\nstudy@concept}#2}
    \noindent{\Large\bfseries\textcolor{defc}{\nstudy@concept}}\ \ {\Large\bfseries #2}\hfill{\small\textcolor{mute}{\nstudy@srcprefix#3}}\par\vspace{1pt}{\color{defc!30}\hrule height 0.5pt}\vspace{2pt}}
    {\nstudy@writeconcept{\nstudy@concept}{\nstudy@tag}\gdef\nstudy@concept{}}
\fi

%% ---------------------------------------------------------------- the six blocks
%% definition (alias formula) | method{caption} | reflex | worked{caption}
%% | traps | practice. Courses show all six; sheets show 1-3 only.
\ifnstudy@sheet
  \newenvironment{definition}{\nstudy@record{1}%
    \begin{tcolorbox}[enhanced,before upper={\raggedright},frame hidden,colback=defc!5,boxrule=0pt,arc=1pt,left=3pt,right=3pt,top=1pt,bottom=1pt,before skip=1pt,after skip=2pt]\small}
    {\end{tcolorbox}}
  \newenvironment{method}[1]{\nstudy@record{2}%
    \par{\color{methc}\sffamily\bfseries\scriptsize \studysheetlabelmethod{} #1}
    \begin{tcolorbox}[enhanced,before upper={\raggedright},frame hidden,borderline west={1.2pt}{0pt}{methc!55},colback=white,boxrule=0pt,arc=0pt,left=5pt,right=2pt,top=0pt,bottom=0pt,before skip=0pt,after skip=2pt]\small}
    {\end{tcolorbox}}
  \NewDocumentEnvironment{reflex}{+b}{\nstudy@record{3}%
    \par{\small\bfseries\textcolor{reflc}{\studysheetlabelreflex\ \ }\textcolor{ink}{\nstudytrim{#1}}}}{}
  \NewDocumentEnvironment{worked}{m +b}{\nstudy@record{4}}{}
  \NewDocumentEnvironment{traps}{+b}{\nstudy@record{5}}{}
  \NewDocumentEnvironment{practice}{+b}{\nstudy@record{6}}{}
  \newcommand{\studynote}[1]{}
\else
  \newenvironment{definition}{\nstudy@record{1}%
    \nstudy@label{defc}{1}{\studylabeldefinition}\nstudy@afterlabel
    \begin{tcolorbox}[enhanced,before upper={\raggedright},breakable,colback=defc!3,colframe=defc!55,boxrule=0.5pt,arc=2pt,left=7pt,right=7pt,top=4pt,bottom=4pt,before skip=0pt,after skip=4pt]}
    {\end{tcolorbox}}
  \newcommand{\nstudy@rail}[1]{enhanced,before upper={\raggedright},breakable,frame hidden,borderline west={1.6pt}{0pt}{#1!60},colback=#1!2.5,boxrule=0pt,arc=0pt,left=9pt,right=5pt,top=3pt,bottom=3pt,before skip=0pt,after skip=4pt}
  \newenvironment{method}[1]{\nstudy@record{2}%
    \nstudy@label{methc}{2}{\studylabelmethod}\nstudy@caption{#1}\nstudy@afterlabel
    \expandafter\tcolorbox\expandafter[\nstudy@rail{methc}]}
    {\endtcolorbox}
  \newenvironment{reflex}{\nstudy@record{3}%
    \nstudy@label{reflc}{3}{\studylabelreflex}\nstudy@afterlabel
    \begin{tcolorbox}[enhanced,before upper={\raggedright},frame hidden,colback=reflc!8,boxrule=0pt,arc=2pt,left=7pt,right=7pt,top=3pt,bottom=3pt,before skip=0pt,after skip=4pt]\bfseries}
    {\end{tcolorbox}}
  \newenvironment{worked}[1]{\nstudy@record{4}%
    \nstudy@label{examc}{4}{\studylabelworked}\nstudy@caption{#1}\nstudy@afterlabel
    \expandafter\tcolorbox\expandafter[\nstudy@rail{examc}]}
    {\endtcolorbox}
  \newenvironment{traps}{\nstudy@record{5}%
    \nstudy@label{trapc}{5}{\studylabeltraps}\nstudy@afterlabel
    \expandafter\tcolorbox\expandafter[\nstudy@rail{trapc}]}
    {\endtcolorbox}
  \newenvironment{practice}{\nstudy@record{6}%
    \nstudy@label{pracc}{6}{\studylabelpractice}\nstudy@afterlabel
    \expandafter\tcolorbox\expandafter[\nstudy@rail{pracc}]}
    {\endtcolorbox}
  %% \studynote{text}: a small muted note under a concept (course only).
  \newcommand{\studynote}[1]{\par\vspace{2pt}{\footnotesize\textcolor{mute}{\textit{\nstudy@notelabel} #1}}}
\fi
\let\formula\definition
\let\endformula\enddefinition

%% Material for one variant only, so one source feeds both.
\ifnstudy@sheet
  \newcommand{\courseonly}[1]{}\newcommand{\sheetonly}[1]{#1}
\else
  \newcommand{\courseonly}[1]{#1}\newcommand{\sheetonly}[1]{}
\fi

%% ---------------------------------------------------------------- appendix
%% \studyappendix{title}{intro} then \studyslip{number}{text} per item.
\newcommand{\studyappendix}[2]{%
  \clearpage\phantomsection\addcontentsline{toc}{section}{Appendix: #1}
  {\noindent\LARGE\bfseries Appendix --- #1\par}\vspace{6pt}{\color{defc}\hrule height 1pt}\vspace{4pt}
  \small #2\par\vspace{4pt}}
\newcommand{\studyslip}[2]{\par\noindent\hangindent=2.6em\hangafter=1\textbf{#1}\ \ #2}

\endinput
