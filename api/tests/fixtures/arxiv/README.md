# arXiv test fixtures

Responses recorded from arXiv, used so that tests never touch the network.

| File | What |
|---|---|
| `by_id.xml`, `search_recent.xml`, `missing_id.xml`, `bad_query.xml` | arXiv API responses. arXiv metadata is CC0. |
| `html_2401.04088v1.html` | Excerpt of the arXiv HTML of *Mixtral of Experts*, Albert Q. Jiang et al., [arXiv:2401.04088v1](https://arxiv.org/abs/2401.04088v1), licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Trimmed to the title, abstract, sections 1–2 and two references; scripts, styles, images and navigation removed. |
| `pdf_2310.06825v1_p1-2.pdf` | Pages 1–2 of *Mistral 7B*, Albert Q. Jiang et al., [arXiv:2310.06825v1](https://arxiv.org/abs/2310.06825v1), licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). |

Full-text fixtures must come from papers under CC BY or CC0, be cut down to what the tests need, and be listed here with their source and license.
