# Skill data: sources, licences and changes

careerfit's skill list has two parts. `skills.yaml` is written by hand. `skills_imported.yaml` adds
technology skills that `scripts/import_taxonomy.py` generates from the two open datasets below. Both
datasets are **modified** by careerfit: the changes are listed at the end, and
`IMPORT_MANIFEST.yaml` records, for every rule, how many names it kept or dropped and which ones.

## O*NET®

This page includes information from the O*NET 31.0 Database by the U.S. Department of Labor,
Employment and Training Administration (USDOL/ETA). Used under the CC BY 4.0 license. careerfit has
modified all or some of this information. USDOL/ETA has not approved, endorsed, or tested these
modifications.

- Data: the O*NET® 31.0 "Software Skills" file, https://www.onetcenter.org/database.html
- Licence: Creative Commons Attribution 4.0, https://creativecommons.org/licenses/by/4.0/
- O*NET® is a trademark of USDOL/ETA.

## ESCO

This service uses the ESCO classification of the European Commission.

- Data: ESCO v1.2.1, English, the digital skills collection (`digitalSkillsCollection_en.csv`),
  https://esco.ec.europa.eu/en/use-esco/download
- Reuse: free of charge for any purpose under Commission Decision 2011/833/EU. careerfit uses a
  **modified and adapted version** of ESCO, as listed below. The Commission does not guarantee
  that ESCO is accurate, up to date or complete.

## What careerfit changed

- **Selection.** O*NET: only technology names used by computer occupations (SOC 15-*), or flagged
  Hot Technology or In Demand. ESCO: only "knowledge" concepts of the digital skills collection.
- **Names.** Lowercased; a trailing "software" and ESCO's tags in parentheses removed; an acronym
  spelled out by the words before it replaces them ("learning management system LMS" becomes "lms",
  with the phrase as an alias, unless the phrase opens with "a", "an" or "the"); a parenthetical
  acronym and a vendor-free form ("photoshop" for "Adobe Photoshop", from O*NET and ESCO names
  alike) added as aliases.
- **Drops.** Everyday words ("spark", "database"), O*NET category labels, names over 5 words or
  40 characters, names about knowledge of a topic ("concepts of telecommunications"), and anything
  already in careerfit's hand-written list, a vendor's form of it included ("Oracle PL/SQL"), but
  not a vendor's product with a generic name ("Amazon Data Pipeline" is not data pipelines).
- **Merges.** One tool under two names becomes one skill ("hadoop" and "Apache Hadoop"; an ESCO
  label that O*NET names too; a plural of several words and its singular, "learning management
  systems" and "LMS"). A vendor's product stays apart from the discipline its other words name
  ("SAP Business Intelligence" is not "business intelligence") unless a person merged them.
- **Corrections** in `import_overrides.yaml` (drops, renames, allowed aliases) apply to the names
  as the sources give them, before any automatic merge.
- **Aliases from ESCO** are kept only when a person allowed them in `import_overrides.yaml`.
