# Repository acceptance baseline

This baseline intentionally re-establishes the last-touch commit for all tracked paths after the integration of earlier feature branches. The preceding archival tree records the complete prior source snapshot; both commits are appended to the existing history without a force push. The archival commit is a history-only staging snapshot, not a runnable release. The restored tree preserves all source blobs except the explicit CI trigger and documentation changes in this baseline.

The check result of this baseline must come from actual CI execution. Previous failures and cancelled checks remain in history and are not overwritten. A pending check is not a pass. Both maintained branches must run the full acceptance suite; the file audit records historical or current status without fabricating results.
