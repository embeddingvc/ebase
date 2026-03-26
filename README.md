### Goal

Build an automated outreach system that:

- Generates personalized outreach strategies
- Executes multi-step outreach sequences (LinkedIn)
- Tracks outcomes and optimizes based on response signals

### Problem Statement

Manual cold outreach is time-consuming and inconsistent. Operators must repeatedly:

- research prospects
- personalize messages
- decide next steps based on prior conversation state
- perform repetitive UI actions
- track outcomes across fragmented tools

### Scope

- Prospect profile navigation
- Conversation history retrieval and summarization
- Personalized message generation
- Message sending through browser automation
- Social engagement actions such as reactions, lightweight comments, and post interaction
- Conversation state tracking
- Resume or attachment download and storage when available
- Action logging and sequence progression

This project is meant for operator to initiate a connect request to linkedin account with a target url and successfully retrieving email/resume/scheduled calls without human input on linkedin other than authentication.

### Success Criteria

**Primary Metrics**

- reply rate
- positive reply rate
- meeting conversion rate
- resume collection rate
- manual intervention rate

**Operational Metrics**

- successful navigation rate
- successful message send rate
- automation error rate
- account restriction / warning rate

**Quality Metrics**

- duplicate / low-quality personalization rate
- state tracking accuracy

### Challenges

- Linkedin bot detection
    - Mitigated with new accounts and VPN as short term fix.
- Unstable conversation state tracking in openclaw
    - Store explicit states in file
- Social engineering
    - Identify posts to react and comment to gain connection depth
    - Experiment with outreach time and response interval
- Separation of Reasoning and Action
    - Consider making actions more deterministic
    - This makes integration test easier since message content is platform independent

### Tech Stack

- Openclaw
- Playwright

### Skills

- Skill that takes profile, conversation history as input and output a message with side effect of marking the conversation as ended and storing the resume.
- Skill that performs resume file download.
- Skill that navigates user profile.
- Skill that send message to a user.
- Skill that emote under target posts and comment on the post.

### Exploration

---

**Openclaw**

Pros:

- Quick protyping
- Ease of use

Cons:

- Unstable
- Recomputation for every action

---

**Claude Cowork**

Pros:

- 

Cons:

- 

---

**Playwright**

Pros:

- 

Cons:

- 

---

**chrome-devtools-mcp**

Pros:

- 

Cons:

- 

---

### Accounts

| **Email** | **Password** |
| --- | --- |
| nova94460@gmail.com | … |
|  |  |

### Action items

- [ ]  define the canonical prospect and conversation schemas
- [ ]  split skills into message planning, execution, and state update categories
- [ ]  create more throwaway accounts to test linkedin integration skills
- [ ]  add action logging and evidence capture for every browser interaction
- [ ]  explore browser automation tools
