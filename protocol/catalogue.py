"""Audited behaviour-controls/1 catalogue; no runtime ML dependency."""
CATALOGUE = []
for i in range(20):
    CATALOGUE.append(dict(directness=['moderate','high'][i%2], warmth=['low','moderate','high'][(i//2)%3],
        verbosity=['low','moderate','high'][(i//6)%3], humour='moderate' if i in (3,9,15) else 'low',
        formality='high' if i%4==0 else 'moderate', explanation_depth=['low','moderate','high'][(i//6)%3],
        assertiveness='moderate'))

