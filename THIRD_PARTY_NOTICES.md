# Third-party software and provenance

AlphaMaxxin's original code and research skills are covered by the root
[MIT license](LICENSE), copyright 2026 yeebs1000. This license does not
relicense third-party dependencies, services, or separately installed tools.
Python dependencies are listed in [requirements.txt](requirements.txt) and
[backend/requirements-backend.txt](backend/requirements-backend.txt);
frontend packages are recorded in [frontend/package.json](frontend/package.json)
and [frontend/package-lock.json](frontend/package-lock.json). Each package's
own license applies.

## Optional moomoo agent skills

Earlier revisions copied `moomooapi` and `install-moomoo-opend` under
`.claude/skills/` from Futu/moomoo's official distribution. Their upstream
sources are [Moomoo Agent Hub](https://github.com/MoomooOpen/moomoo-agent-hub)
and the [official OpenD skills archive](https://openapi.moomoo.com/skills/opend-skills.zip).

The copied skills identify **Futu** as their author in `SKILL.md` metadata
(version 0.1.1). The official upstream
[README at commit 5e3572de8028729d8d6984e3719a26a23bc77dd7](https://github.com/MoomooOpen/moomoo-agent-hub/blob/5e3572de8028729d8d6984e3719a26a23bc77dd7/README.md#license)
declares **MIT** and credits Futu. Its linked separate `LICENSE` file was
unavailable when checked on 2026-10-06, and the copied files and official
archive supplied no separate vendor copyright or license notice. The
attribution here comes from the skill metadata; the license declaration
comes from the upstream README. No vendor copyright year is inferred.

The vendor files remain in earlier Git history. This notice preserves their
Futu attribution and records the upstream-declared MIT permission terms
below. They are excluded from the current source distribution so the
included agent tooling matches AlphaMaxxin's read-only broker scope.

If desired, install the vendor tools separately using the
[official instructions](https://github.com/MoomooOpen/moomoo-agent-hub#quick-start)
and review the terms provided by the vendor. They support trading actions,
including placing, modifying, and cancelling orders. AlphaMaxxin's app
uses the Python SDK for read-only broker queries and does not require
these agent skills.

### MIT permission terms for the historical vendor copies

The standard MIT text below records the license declared by upstream; it
does not replace any additional notice the vendor may supply later.

```text
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
