# User guide: the iTop assistant

The **iTop assistant** lets you ask questions about iTop in a chat, in plain language: "Which user
requests are open?", "Show me R-000123", "Which servers do we have?". It looks the answers up in
iTop for you.

This guide shows you how to log in, connect the assistant to your iTop account once, and ask good
questions. It takes about five minutes.

> The screenshots come from a test system. Your company's addresses, names and button labels may
> differ slightly. Your administrator tells you the address of the chat.

## Contents

1. [What the assistant can and cannot do](#1-what-the-assistant-can-and-cannot-do)
2. [Log in to the chat](#2-log-in-to-the-chat)
3. [Connect to iTop (once)](#3-connect-to-itop-once)
4. [Ask questions](#4-ask-questions)
5. [Your connection](#5-your-connection)
6. [Privacy](#6-privacy)
7. [Questions and problems](#7-questions-and-problems)

## 1. What the assistant can and cannot do

**It can:**

- find tickets by text, status and type (user requests, incidents, changes, problems)
- show one ticket with its description and, for user requests and incidents, its public log
- list configuration items such as servers, applications or locations
- tell you which iTop account it is using

**It cannot:**

- **change anything in iTop.** It only reads. It cannot create, update, assign or close tickets.
  Do that in iTop as usual.
- **see more than you.** It works with your own iTop account and your own iTop rights. What you
  cannot open in iTop, the assistant cannot read either.

The assistant is an AI. It is usually right, but it can misread or summarise wrongly. Before you
act on an answer, for example call a customer, open the ticket in iTop and check.

## 2. Log in to the chat

Open the chat address your administrator gave you, for example `https://chat.example.com`, and
click **Sign in with Keycloak** (your company may call this button differently, for example after
its login portal).

![Chat login page with "Sign in with Keycloak"](images/user-guide/01-librechat-login.png)

Log in with your usual company account. If you are already logged in elsewhere in the company, this
page may be skipped.

![Company login page: username or email, password](images/user-guide/02-keycloak-login.png)

You are now in the chat. New chats normally start with the **iTop assistant** already selected (at
the top) and with **iTop** switched on (the small **iTop** chip in the input field):

![Chat start page with "iTop assistant" selected and the iTop chip in the input field](images/user-guide/03-librechat-home.png)

## 3. Connect to iTop (once)

The first time, the chat needs your permission to read iTop for you. You give it once; after that
it works in the background.

**1. Start the connection.** Either ask the assistant a question, and it shows a **Sign-in**
button right in the chat:

![Chat: "Requires Authentication in itop" with a Sign-in to itop.example.com button](images/quick-start/12-librechat-sign-in-in-chat.png)

or click the **MCP Settings** icon in the left bar and then the **Connect** icon (the plug) next to
**iTop**:

![MCP Servers panel: iTop with an orange dot and the Connect icon](images/quick-start/07-librechat-mcp-servers.png)

The chat shows the iTop address. Click **Continue with OAuth**:

![Dialog "Connect itop" with the Continue with OAuth button](images/quick-start/08-librechat-connect-dialog.png)

**2. Log in to iTop.** A new browser tab opens with iTop's login page. Log in as you do every day
(with your company account: **Sign in with Keycloak**).

**3. Allow the connection.** iTop asks whether the chat may act as you. Check two things:

- the account (`... wants to act as` **your own login**)
- where you are sent back to: **your company's chat address**

Then click **Allow**. The tab closes by itself.

![iTop page "Connect an application": the chat wants to act as you, sent back to chat.example.com, Allow and Deny](images/quick-start/09-itop-consent.png)

> **Only click Allow if you started the connection yourself, just now.** If you got this page
> through a link from someone else, click **Deny** and tell your administrator.

**4. Done.** The dot next to **iTop** turns green. If you had asked a question in step 1, ask it
again.

![MCP Servers panel: iTop with a green dot](images/quick-start/10-librechat-connected.png)

## 4. Ask questions

Start a **new chat** for each topic (the pencil icon at the top left). Make sure **iTop assistant**
is selected at the top and the **iTop** chip is in the input field.

![Model menu with "iTop assistant"](images/user-guide/04-model-menu.png)

If you use another model, switch iTop on yourself: click **+** in the input field and pick **iTop**
under **MCP Servers**.

![The + menu of the input field with iTop under MCP Servers](images/user-guide/05-plus-menu-mcp-servers.png)

### Examples

**Find tickets:**

![Question "Which user requests are open at the moment? Answer with a short table." and a table of four requests](images/user-guide/06-open-requests.png)

**Read one ticket:**

![Question "Show me the details of R-000002." with title, description, caller, status and priority](images/user-guide/07-ticket-details.png)

**Look up configuration items:**

![Question "Which servers do we have in iTop?" with a list of four servers](images/user-guide/08-servers.png)

Above each answer you see which iTop lookup the assistant used, for example **Ran search_tickets
in itop**. Click the arrow on the right to see exactly what it asked iTop and what came back.

More questions that work well:

| You want | Ask |
|---|---|
| Tickets about a topic | "Are there incidents about VPN?" |
| Tickets by status | "Which changes are new?" |
| One ticket | "What is the status of I-000045, and what is in its public log?" |
| A short overview | "Summarise R-000123 in three sentences." |
| Configuration items | "Which servers do we have?", "Which locations do we have?" |
| Check the account | "Who am I in iTop?" |

For other questions the assistant can also write its own iTop query. If an answer looks
incomplete, ask more precisely or check in iTop.

### Tips

- **Name the ticket reference** (`R-000123`, `I-000045`) when you mean one ticket. It is faster and
  more exact than describing it.
- **Say what you want back:** "as a table", "only the titles", "the five newest".
- **Ask follow-up questions** in the same chat: "And which of these are assigned to nobody?"
- **Large lists are cut off.** The assistant reads at most a fixed number of rows per lookup (50 by
  default). Narrow the question ("only incidents", "only from this week") if you need everything.

### It does not change anything

If you ask it to change something, it tells you that it cannot:

![Question "Close ticket R-000001." and the answer that it lacks permission and you should close it in iTop](images/user-guide/09-read-only.png)

## 5. Your connection

- **How long it lasts.** The connection ends after 90 days, or after 30 days without use. You then
  connect again as in [section 3](#3-connect-to-itop-once).
- **If your iTop rights change**, the assistant follows right away, because it always asks iTop
  with your account. If your iTop account is disabled, the assistant stops working for you within
  an hour at the latest.
- **To disconnect** in the chat: **MCP Settings** icon → **Revoke** (the red icon next to **iTop**).
- **To disconnect** in iTop: your user menu → **My Account** → **My personal tokens** →
  **Connected applications** → **Disconnect**. This also shows when the chat last used your
  connection.

![iTop My Account, My personal tokens: Connected applications with Disconnect buttons](images/user-guide/10-itop-connected-applications.png)

## 6. Privacy

- The chat never sees your iTop password. iTop gives it a token for your account instead, which
  you can withdraw at any time (section 5). The assistant uses it only to read.
- Every lookup the assistant makes in iTop is recorded with your name, the time and what was
  looked up. The token itself is never recorded.
- Your questions and the data iTop returns are sent to the AI model your company has set up for the
  chat. Ask your administrator if you are unsure which data may be used there.

## 7. Questions and problems

| Problem | What to do |
|---|---|
| The assistant answers without looking anything up, or says it has no access to iTop | Check that the **iTop** chip is in the input field (section 4), then ask again in a new chat. |
| The chat keeps showing **Sign-in** or the dot next to **iTop** stays orange | Connect again (section 3). If it keeps happening, tell your administrator. |
| After logging in to iTop you land on iTop's home page instead of the **Allow** page | Close the tab and start the connection again from the chat. If it happens again, tell your administrator. |
| iTop says you are not allowed, before the **Allow** page | Your iTop account has no profile that may use the assistant. Ask your administrator. |
| iTop shows **another person's name** on the **Allow** page | Click **Deny**. Your browser is still logged into iTop as someone else: log out of iTop, then connect again. |
| No results for a ticket you know exists | Check the reference. If it is right, your iTop account may not see that ticket's organisation; check in iTop. |
| The answer seems wrong | Open the ticket in iTop and check. Click the arrow next to **Ran ... in itop** to see what iTop actually returned. |
| Logging in to the chat fails several times in a row | Wait five minutes and try again: the chat blocks repeated logins for a short time. |

For anything else, contact your iTop administrator.
