# Campus Policy Assistant
Technical report for the DS205.3 group coursework
Group members and student IDs: Add the three verified member details before submission.
## 1 Problem and scope
Students may need answers from several academic documents to complete one task. Examination conduct, extenuating circumstances and repeat coursework are published separately. A language model can give a plausible response without identifying the rule, date or document that supports it. A broad search can also return strong evidence for one part of a question and leave the second unresolved. Campus Policy Assistant gives source-linked answers and can search again for uncovered parts.
The corpus consists of three PDFs distributed through the NSBM Examinations site [1]. The exam instructions have an August 2015 approval date, and the EC guide is a revision from August 2023. The system answers from these dated documents. Current administrative instructions can differ. Other topics, such as parking and accommodation, fall outside the corpus.
A selected source can support the answer text while failing to address the question. A short answer can also look relevant while relying on the wrong source. The design logs search decisions before showing the answer, retains page references and measures these outcomes separately.
## 2 Data pipeline and architecture
> FIGURE 1   FROM PDF PAGES TO A CITED ANSWER
> PDF → page text → overlapping chunks → dense vectors → SQLite
>                                chunk text → TF-IDF on load ↓
> Question → hybrid retrieval → evidence check → cited answer
>                  ↑                    ↓               ↓
>                  └── focused query if evidence is weak  Run log
The system extracted 63 chunks from 12 physical PDF pages when tested with Python 3.12.16 and pypdf 6.13.0 [2]. Ingestion removes soft hyphen line breaks and extraction placeholders, joins split numerical ordinals and produces page-bounded windows of at most 120 words. Long paragraphs use sentence-aware boundaries with up to 20 words of overlap. Each chunk retains its filename, page and identifier. Page boundaries make citations straightforward, although clauses that continue across pages may be split. The macOS PDFKit fallback can produce different chunks because its reading order differs.
<page>
## 3 Mathematical foundations
Vocabulary and term frequency form the sparse representation. Let c(t,d) be term t’s count in chunk d. The nonzero term-frequency weight is 1 + ln(c(t,d)), which dampens repeated words. Let N be the number of chunks and df(t) the number containing t. Inverse document frequency is 1 + ln((N + 1)/(df(t) + 1)). Their product gives the sparse weight. Terms that occur in fewer chunks contribute more to comparing a question and a source passage.
The dense branch uses a trained 512-dimensional Apple English sentence embedding in the semantic profile [3]. The offline profile uses a deterministic 384-dimensional signed hashing representation over words and adjacent word pairs after limited synonym normalization. The optional Ollama profile supports neural embeddings and model-generated answers [4]. The measured semantic and offline modes use selected PDF excerpts as their synthesis method. Live Ollama generation was unavailable for verification and is excluded from these results.
Cosine similarity divides the dot product by the product of vector magnitudes. This normalization accounts for scale. If either magnitude is zero, the score is zero. The score combines max(0, dense cosine) with sparse TF-IDF cosine. Offline assigns 0.65 and 0.35 to dense and sparse respectively. Semantic assigns 0.35 and 0.65. The comparison measures complete profiles because the weights differ.
SQLite stores the model identifier, vectors, source metadata and run records. It rejects an incompatible index and replaces entries in a transaction. HybridRetriever builds the sparse vocabulary from the index and scores both representations. Agent accepts search and synthesis implementations through dependency injection. The command-line module connects the components.
## 4 Agentic loop and traceability
Observation logs candidates, pages, dense dot products, vector magnitudes, cosine scores and combined rank scores. Reasoning checks whether the top source covers each part of the question using normalized terms and nearby sentences. Questions asking when require a timing cue. Three matched concepts and a strong retrieval score can relax the overlap threshold for longer questions.
Action constructs a focused query for each uncovered part and searches again within a bounded budget. Synthesis presents selected evidence or identifies what remains unresolved. Persistence saves the question, trace, evidence and response. In N13 the semantic profile searched three times and cited the exam regulations for the phone policy and the repeat coursework guide for registration.
<page>
## 5 Evaluation method and results
There are 15 development queries and 10 additional challenge cases. Each labeled record has a question, expected answer, reference passage and required facts. The sets contain direct questions, paraphrases, a compound query and absent-policy controls. Both sets informed iteration. The figures describe a small corpus and benchmark.
Context Relevance is the F1 balance between selected-evidence precision and reference-passage recall. A valid alternate source can satisfy a label. Groundedness checks whether claims map to an exact retrieved quote and pass lexical, numerical and polarity checks. It is N/A when the system produces no factual claim. Answer Relevance measures how many labeled facts and expected unresolved parts appear in the response. Exact phrase matching can reject a valid paraphrase. The grounding check measures source support rather than question coverage.
| Profile / dataset            Context    Groundedness    Answer
| Offline / development (15)    1.000       1.000          0.933
| Semantic / development (15)   0.933       1.000          0.867
| Offline / challenge (10)      0.600       1.000          0.500
| Semantic / challenge (10)     0.700       1.000          0.600
Groundedness denominators were 14 and 13 for offline and semantic development respectively. Each challenge mode returned factual claims on six questions. For H01 the system retrieved the correct page and offered an instruction to wait for permission to enter. It missed the requested late-entry limit. For N11 the agent found the right page but omitted the instruction to use the module code or name. These cases explain why the overall answer score is lower than the grounding score.
The next page summarizes the measured semantic answers. E denotes exam regulations, C the EC guide and R the repeat coursework guide. Page numbers refer to physical PDF pages. The final values represent Context Relevance, Groundedness and Answer Relevance. The JSON results include full system answers and passage labels.
<page>
## 6 Semantic development results by question
| Case   Topic and observed response                         C/G/A
N01  Phones in the exam room. Communication devices are prohibited (E p3). 1/1/1
N02  Attract an invigilator. Raise a hand (E p4). 1/1/1
N03  Index number placement. Use the answer book and continuation papers (E p4). 1/1/1
N04  Exam stationery. Insufficient evidence returned (expected E p4). 0/–/0
N05  Smoking in the room. It is prohibited (E p5). 1/1/1
N06  EC deadline. The response identified the 14-working-day window (C p3). 1/1/1
N07  Apply for EC. Submit the EC form and supporting evidence (C p2). 1/1/1
N08  EC and extra marks. A fresh attempt is possible without extra marks (C p2). 1/1/1
N09  Appeal an EC decision. The board’s decision is final under this guide (C p3). 1/1/1
N10  Register for repeat coursework. Use the repeat form and pay the cashier (R p1). 1/1/1
N11  Find a repeat assignment by code. The response gives selection steps and omits code or name search (R p3). 1/1/0
N12  Which payment receipt? Enter the receipt number in the submission form (R p4). 1/1/1
N13  Phones and repeat registration. Both requirements are answered with separate citations (E p3 and R p1). 1/1/1
N14  Buy a parking pass. Insufficient evidence returned. 1/–/1
N15  Repeat submission after download. The response identified the 14-day deadline (R p3). 1/1/1
<page>
## 7 Reflection and future work
A high passage similarity score often supports one part of a compound question. Separation between passage ranking, evidence selection and response scoring made this observable. The two-document query can be demonstrated by following one trace from its first candidates through the final citations. This also shows the cost of evidence gating. Some paraphrases that humans can resolve trigger abstentions because the retrieved evidence shares too few normalized terms with the query.
PDF extraction also influences evaluation. An ordinal in the repeat guide was split into two tokens by one extractor. Normalizing such artifacts improved the phrase checks. Page boundaries make verification easier. Layout-aware reading order, heading labels, cross-page links and table extraction could improve policies with columns or rules extending across pages.
The next evaluation should freeze thresholds before collecting an independent question set. Human reviewers could compare the phrase metric with blind judgments of completeness and factual support. A trained re-ranker or proposition-level evidence check could be tested on compound questions and near misses. A live local generation run would show whether paraphrasing improves clarity or introduces unsupported changes. Logging the proportion of responses that use model text or extractive fallback would make that comparison easier to interpret.
Group reflection entry. Before submission, replace this line with the three members’ actual contributions, one decision each can defend in the viva, and one result or limitation each investigated.
## References
[1] NSBM Examinations. Important Examination Information. https://sites.google.com/view/nsbmexaminations/important-documents-and-announcements
[2] pypdf contributors. Version 6.13.0. https://pypi.org/project/pypdf/6.13.0/
[3] Apple Developer Documentation. NLEmbedding. https://developer.apple.com/documentation/naturallanguage/nlembedding
[4] Ollama API documentation. https://docs.ollama.com/api/embed and https://docs.ollama.com/api/chat
