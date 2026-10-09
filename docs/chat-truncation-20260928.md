# Chat response truncation

The runtime status snapshot compacted dialogue text to 1,200 characters, just
like tool output. Fluxio uses those messages to hydrate and settle transcript
turns, so a refresh could replace the live reply with a completed short preview.
The installed app visibly ended the latest response at the 1,200-character
boundary; its runtime result and stream both retained 2,023 characters.
The previous two results retained 8,052 and 10,501 characters.

Dialogue rows now retain their saved text. Tool previews remain bounded.
Transcript reconciliation also retains a longer received answer when a shorter
prefix arrives, and lets a full completion repair an existing prefix.

Checks: seven Node transcript tests passed. The snapshot integrity check preserves
a 19,213-character answer while keeping tool previews at 1,200 characters.
A read of the affected conversation produced the full saved message lengths
546, 8,046, 291, 10,487, 172, and 2,023 (saved formatting differs from raw streams).

No provider inference or private prompt was needed to reproduce this issue.
