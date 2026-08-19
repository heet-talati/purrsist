# Purrsist

### Description: What is it?

A tiny system that makes you choose what matters, work on it, record what happened, and come back tomorrow.

### Problem

I repeatedly switch what I'm learning before I have enough time to develop competence. I need a simple system that forces me to explicitly choose a small number of priorities, work on them consistently, and leave evidence of what I accomplished.

### Success: How do we know if we’ve solved this problem?

I am able to finish something completely without leaving it in middle, and have learned something new in the process.

### Audience: Who are we building for?

Initially, Me. (post on subreddits to find others facing similar issues.)

### What: Roughly, what does this look like in the product?

It will be a CLI (Command-Line Interface) program, skipping the heavy UI for minimalism, speed and clarity

### How: What is the experiment plan?

1. Maximum 3 active priorities.
2. Working on something is more important than planning it.
3. Consistency matters more than perfect days.
4. Curiosity is allowed but does not automatically change priorities.
5. The system should encourage autonomy rather than punish failure.
6. The user should leave evidence of what they actually accomplished.
7. The tool should be simple enough to use every day.

### When: When does it ship and what are the milestones?

General Ideas - to be clustered into a roadmap later.:

- Goals - things you are working on
- Tracking - Pomodoro Timer (for staying focused) | Start-Stop timer with "still there?" check for longer sessions
- Proof of work - daily log of what was accomplished in simple bullet points, to be done after each session. If daily progress is not logged, cat stays hungry that day and progress is forgotten
- Review/Statistics - daily, weekly, monthly review of what was accomplished using focus sessions & daily logs
- Streaks - for showing up daily (like feeding the cat daily to keep it alive)
- Shiny Object Parking Lot - a place to park ideas that are not currently a priority, but can be revisited later
- Companion - have a CAT character for emotional investment and to make the app more fun
- Auto-Start on boot - i mean.. I will forget the app exists before the habit is fully built. Having the app start on boot will make it easier to use it.
- Keyboard Shortcut - Keyboard combination to instantly start the program, with customizable options.

### Questions: To be converted to feature roadmap

1. What is the first thing the user sees when they open this app for the first time?
2. How will the onboarding look like?
3. What if the user can't figure out or forgot something, how will they look for help?
4. How will the data be stored? Will it be local or cloud?
5. How will the data be loaded onto the app?
6. Will the data be synced periodically for backup?
7. How many active goals can the user have at once?
8. What if the user is only allowed to add another goal if their avg time/day is meeting the required threshold for the goal to be completed by deadline?
9. Does the goal ever expire?
10. Are the goals going to be categorized?
11. Can the user create custom categories for goals?
12. What happens when the user exceed the max active goal limit?
13. Is there a way to put goals in a waiting queue?
14. Can the user track time without assigning it to a goal?
15. What happens if the user don't have any time allocated to a goal for a certain period of time, does the goal become inactive?
16. Does the user get reminders if a goal hasn't had any activity for a certain period of time?
17. How can the user track time for people with focus issues?
18. How can the user track time for people who enter flow state after a certain period of time; without disturbing them?
19. What if the user starts doing things that are not related to goal while in session?
20. How does the user know what they worked on without eventually forgetting?
21. How can the users log their work without spending a lot of time journaling?
22. What if the user finds something really interesting or has a new idea to work on while they already have an ongoing goal?
23. How can they still have it without fear of losing it, to make sure priorities stay undisturbed?
24. If the user finds something new, what if they add a few reasons on why they wanted to do it in the first place to get the context later? (what, why, how it'll help them) 
25. Can the user take an item from this list and move it to active goals?

### Product Roadmap
- MVP (V 1.0.0)
  - Goals
    - As a user, I want to be able to add a Goal so I can see what the current priority is
    - As a user, I want to be able to delete a Goal I no longer need
    - As a user, I want to be able to remove a Goal from current priority
    - As a user, I want to have maximum 3 active goals at a time with one being the priority
    - As a user, I want to be able to view all my active Goals with the priority being highlighted.
    - As a user, I want to set a time limit on a Goal in hours so I know my progress
    - As a user, I want to know the average time spent on a goal/day after 7 days so I know how long it will take to reach the end at current pace
  - Tracking (Pomodoro only)
    - As a user, I want to track time for my goal using a timer preset
    - As a user, I want to be able to pause and resume my timer
    - As a user, I want to be able to end my timer
    - As a user, I want to receive a visual cue when my timer ends
    - As a user, I want to know which goal is my timer for so I know what is being tracked
  - Daily Logging
    - As a user, I want to be able to backtrack what I worked on with logs
    - As a user, I want to write a simple line to document what I did in the timer period
    - As a user, I want to be able to edit my log
    - As a user, I want to view all my logs
    - As a user, I want to be able to filter my logs by periods (session, day, goal)
