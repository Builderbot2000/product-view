"""Prompts for the issue stage.

The complaint prompts are the ones validated on 2026-10-13 (llm-trials.md,
"Viability test", re-run with selection): do not reword them without
re-running that test. Examples come from an unrelated domain (food delivery),
because the model copies example wording into its answers.

The praise prompts mirror them for liked features and are NOT yet validated.
"""

DISTILL = """You read Google Play reviews of a mobile app and pull out every point the reviewer makes about the app: each complaint and each piece of praise.

Rules:
- Copy each point as an exact quote from the review: the shortest run of consecutive words that still makes sense on its own. Do not reword, fix spelling or translate.
- One entry per distinct point. Keep a complaint whole: a cause with its effect, an error message with the action that triggered it.
- Tag each entry "complaint" (something wrong, missing or disliked, sarcasm included) or "praise" (something that works or is liked).
- Include general opinions too ("worst app ever", "love it"); a later step sorts specific from general.
- Return an empty list if the review makes no point about the app.

Example from another domain. Review: "Love the restaurant choice but the driver map freezes every time and support never answers. 2 stars"
-> {"quote": "Love the restaurant choice", "kind": "praise"}, {"quote": "the driver map freezes every time", "kind": "complaint"}, {"quote": "support never answers", "kind": "complaint"}"""

SUMMARIZE = """You rewrite points quoted from a review of a mobile app as short neutral bullets.

For each numbered quote, write one bullet of 4-10 words that says what the point is about and what happens, in plain neutral words. Drop tone, insults and sarcasm. Use the review for context (what "it" refers to) but add nothing it does not say. Write in English.

Examples from another domain:
- "the driver map freezes every time" -> "driver tracking map freezes"
- "support never answers" -> "support does not respond to messages"
- "Love the restaurant choice" -> "wide choice of restaurants"
- "worst app ever lol" -> "general dislike of the app\""""

SYNTHESIZE = """You find the specific problems in a group of points taken from reviews of a mobile app.

You see a numbered list of short points grouped because their wording is similar. The grouping is rough: a group often mixes two or three different problems, plus general opinions and one-offs.

Return one concept for each specific problem in the list that two or more points describe. Pitch each concept at the level one product team would own: points about the same feature with the same kind of failure belong together even when the details differ (old phones, tablets and a new phone model are all "app not supported on this device"). Keep different features apart even when the symptom is the same. For each concept:
- feature: the one part of the app it is about: a screen, an action, a setting, or a kind of device (1-4 words). Never "the app" as a whole unless the points are about the app failing to open or run at all.
- failure: the one thing that goes wrong with it (1-6 words).
- name: 2-6 words joining the two, specific enough that a product team knows where to look ("Driver map freezes", not "App problems").
- criterion: one sentence starting "The point says" that names that feature and that failure. Do not join different features or failures with "or" to cover more points.
- points: the numbers of every point that describes this problem.
Leave out general opinions, feelings and one-offs; they are handled later. Return an empty list only if the points are all general opinions or all different.

Example from another domain. Points: 1. driver map freezes 2. map stops updating during delivery 3. app crashes at checkout 4. live tracking map never loads 5. terrible service 6. checkout crashes when paying by card 7. app closes when I tap pay
-> {"feature": "driver map", "failure": "freezes or stops updating", "name": "Driver map freezes", "criterion": "The point says the live map tracking the driver freezes, stops updating or never loads.", "points": [1, 2, 4]}
-> {"feature": "checkout", "failure": "app crashes", "name": "Checkout crashes on payment", "criterion": "The point says the app crashes or closes while the user is paying at checkout.", "points": [3, 6, 7]}
(5 is a general opinion and is left out.)
Points: 1. app won't run on my old phone 2. not available for my tablet 3. doesn't support the new Pixel 4. app says device not compatible
-> one concept: {"feature": "device support", "failure": "app not supported", "name": "App not supported on some devices", "criterion": "The point says the app does not install, run or appear as available on the user's phone, tablet or device model.", "points": [1, 2, 3, 4]}"""

BREADTH = """You judge one concept found in reviews of a mobile app. Pick one answer:
specific: it names one feature (a screen, an action, a setting, a kind of device or connection, or the app failing to open or run at all) and one kind of failure, so one product team would know where to look. Two wordings of the same failure joined by "or" are still specific ("fails or is blocked", "freezes or stops updating").
broad: it names no single feature (the app as a whole is buggy, slow, has errors, malfunctions or does not work), or it joins two different features ("checkout or tracking").
general: a feeling or opinion (frustration, annoyance, embarrassment, regret, distrust) about the app, a process, the company or its service, naming no fault; or the quality of customer support.

Examples from another domain:
- "Driver map freezes": the point says the live driver map freezes or stops updating -> specific
- "Promo code rejected or not applied": the point says a promo code is refused or has no effect at checkout -> specific
- "App crashes on startup": the point says the app closes as soon as it is opened -> specific
- "App is buggy and slow": the point says the app has bugs, errors or performance problems -> broad
- "App shows errors and crashes": the point says the app crashes or shows error messages, with no screen or action named -> broad
- "App still broken after reinstalling": the point says reinstalling did not fix the app -> broad
- "Checkout or tracking fails": the point says checkout fails or the driver map does not load -> broad
- "Checkout is frustrating": the point says paying is annoying or stressful -> general
- "Support is unhelpful": the point says support staff do not solve the problem -> general"""

CONFIRM = """You check whether two concepts found in reviews of a mobile app are duplicates.

They are duplicates only if they are about the same feature (the same screen, action, setting or kind of device) and the same kind of failure. Different actions are different features even when both involve the same step, such as a verification check. Sharing a symptom (both crash, both show an error) is not enough.

Examples from another domain:
- "Driver map freezes" / "Live tracking stops updating" -> same
- "Promo codes rejected" / "Card payment declined at checkout" -> different (both at checkout, different features)
- "Driver map freezes" / "App crashes at checkout" -> different"""

SCORE = """You check points taken from reviews of a mobile app against one concept.

Concept: {name}
Criterion: {criterion}

For each numbered point, pick one answer:
A: the point is about the feature in the criterion and describes the failure in the criterion.
B: the point describes a clear case of it in other words (a named device for a device problem, a named step of the same action).
C: a near miss: the same feature with a different failure, or the same failure (crash, error, loop) on a different feature.
D: about something else.
E: a general opinion or feeling that names no specific feature or fault.
Judge only what the point says. Sharing a word or a symptom is not enough: a crash while scanning an ID is C for a concept about crashes on older phones."""

# Appended to SCORE / SCORE_PRAISE when scores come back as a bare list of
# letters (issues.compact_scores) instead of {n, answer} objects.
COMPACT = "\nAnswer with one letter per point, in the order of the points."

# --- praise (not yet validated) ------------------------------------------------

SYNTHESIZE_PRAISE = """You find the specific things users like in a group of points taken from reviews of a mobile app.

You see a numbered list of short points grouped because their wording is similar. The grouping is rough: a group often mixes two or three different things, plus general praise and one-offs.

Return one concept for each specific liked thing in the list that two or more points describe. Pitch each concept at the level one product team would own: points about the same feature liked for the same reason belong together even when the details differ. Keep different features apart. For each concept:
- feature: the one part of the app it is about: a screen, an action, a setting, or a kind of device (1-4 words). Never "the app" as a whole.
- liked: what users like about it (1-6 words).
- name: 2-6 words joining the two, specific enough that a product team knows what is working ("Live driver map is accurate", not "Great app").
- criterion: one sentence starting "The point says" that names that feature and what is liked about it. Do not join different features with "or" to cover more points.
- points: the numbers of every point that describes this.
Leave out general praise ("great app", "easy to use", "love it") and one-offs; they are handled later. Return an empty list only if the points are all general praise or all different.

Example from another domain. Points: 1. live map shows driver accurately 2. great app 3. reorder button saves time 4. can track the courier in real time 5. one tap to repeat last order
-> {"feature": "driver map", "liked": "accurate live tracking", "name": "Live driver map is accurate", "criterion": "The point says the live map tracking the driver is accurate or updates in real time.", "points": [1, 4]}
-> {"feature": "reorder", "liked": "repeats an order quickly", "name": "Quick reorder", "criterion": "The point says the user can repeat a previous order quickly, such as with one tap.", "points": [3, 5]}
(2 is general praise and is left out.)"""

BREADTH_PRAISE = """You judge one concept found in positive reviews of a mobile app. Pick one answer:
specific: it names one feature (a screen, an action, a setting, a kind of device) and what users like about it, so one product team would know what is working.
broad: it names no single feature (the app as a whole is good, easy, fast or convenient), or it joins two different features ("checkout or tracking").
general: an opinion or feeling about the app, the company or its service, naming nothing specific ("great app", "love it", "good service").

Examples from another domain:
- "Live driver map is accurate": the point says the driver map is accurate or updates in real time -> specific
- "Quick reorder": the point says the user can repeat a previous order with one tap -> specific
- "App is easy and fast": the point says the app is simple, quick or convenient -> broad
- "Great app": the point says the app is great -> general"""

CONFIRM_PRAISE = """You check whether two concepts found in positive reviews of a mobile app are duplicates.

They are duplicates only if they are about the same feature (the same screen, action, setting or kind of device) and users like the same thing about it. Sharing a word of praise (both "easy", both "fast") is not enough.

Examples from another domain:
- "Live driver map is accurate" / "Courier tracking updates in real time" -> same
- "Quick reorder" / "Fast checkout" -> different (different features)"""

SCORE_PRAISE = """You check points taken from positive reviews of a mobile app against one concept.

Concept: {name}
Criterion: {criterion}

For each numbered point, pick one answer:
A: the point is about the feature in the criterion and likes the thing in the criterion.
B: the point describes a clear case of it in other words.
C: a near miss: the same feature liked for something else, or the same kind of praise about a different feature.
D: about something else.
E: general praise that names no specific feature.
Judge only what the point says. Sharing a word ("easy", "fast") is not enough."""

# --- areas (both sides) ----------------------------------------------------------

AREA = """You file one concept found in reviews of a mobile app under the product area that would own it.

Areas:
{areas}

Pick exactly one area id. Use the area for the app's own functions (the things it exists to do) when no other area fits better."""
