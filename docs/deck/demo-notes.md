# Demo Notes

**Background (~5 min)**

1. I was drawing up ideas for new PoCs and thought I'd check Google Play Store reviews first for pain points. [Show the thousands of reviews for the app on the Play Store]
2. I figured the product team would already be doing something similar, so I asked about their workflow. [Show Slack message]
3. It turned out the product team was handling reviews by hand, with a bot that auto-posts them to Slack. [Show the Slack channel with the bot]
4. I had an idea to organize these reviews into readable reports, and asked the product team manager if they'd like something like this. [Show Slack conversation]
5. The manager said they had something like this for the internal feedback hub but nothing for the Google Play Store, and gave me a request. [Show more of the Slack conversation]
6. I interviewed the developer who built the AI-driven report for the internal feedback hub. That tool writes one summary of all the feedback, which works well for the feedback hub. The product team asked for something different: each person sees only the features they own, with how many reviews mention each one. One summary can't be split that way, so I built this to do it. [Show the reference project]

**Content (~13 min)**

7. Introduce the report the PoC prototype produced, and how it will be delivered. This example covers a month's worth of reviews from earlier this year.
   - [On the member report] Product team members can spot user pain points on the features they own.
   - [On the team page] Analysts get the reviews counted and grouped by feature, ready for them to draw their own conclusions.
8. Show the PoC code briefly, then explain how it works using the diagram: reviews come in → sorted by each team's features → report built → each person gets an email. [Show the code, then the diagram in the reference]
9. Today this runs on my laptop. What the product team asked for is a report in each person's inbox every week, with no one running it by hand. For that it needs to run on RBC's cloud. That's where the projects shown at the last Agent Builder Open Session run, and it has the approved AI model, scheduling and email this needs. I'm asking for your support to get access.

**Free Discussion (~12 min)**

---

Before the meeting:
- Open every screen in order in its own tab.
- Check with the product team manager that it's OK to show their Slack messages.
