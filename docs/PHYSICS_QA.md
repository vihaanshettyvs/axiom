# Physics Q&A cheat sheet (P2)

Say first: **"The physics is simplified and everything is simulated, except the fire data."**
Detail for every answer is in `docs/ASSUMPTIONS.md`.

## 1. Time-compressed ground tracks
**Q: Real LEO satellites don't cross a 100 km region every ~110 minutes. Why does yours?**
A: We model a locally linearised nadir track over the region of interest. The in-region period is
compressed so the 3-hour demo shows several passes. Physical altitude (550 km) is a separate
parameter, used only by the drag and retirement models. This is a demo choice, not an orbit solution.

## 2. Scripted conjunctions
**Q: Your debris encounters are scripted. Is this collision prediction?**
A: No. It is not an operational conjunction system. The events are fixed so that brain ON and OFF
face the same world. Each event still gets a physical form: Pc = 0.5 * exp(-0.5 (miss/sigma)^2),
with miss distance back-solved from the scripted Pc, and random relative speed, size and covariance
from a seeded RNG. Risk = Pc x consequence.

## 3. Dodge fuel and effectiveness
**Q: Why is an early dodge cheaper and better?**
A: An along-track burn moves the miss distance by about 3 x dv x t, so the same shift needs less
delta-v with more lead time. Fuel follows the rocket equation. Effectiveness rises with lead because
more of the required shift is achieved.
**Q: Are those numbers measured?** A: No. The constants (200 kg, Isp 50 s, 2.4 km shift, 21 min arc)
were calibrated to the mock's curve within about 10% over 0-90 min lead. The shape (early is cheaper)
is physics; the exact values are tuned. We say so.

## 4. Space weather
**Q: What does the slider do?**
A: One index, 0 to 1 (0.5 nominal). It scales atmospheric density by 10^(2(w-0.5)) (x0.1 to x10)
and wear by 1+(w-0.5). More density shortens drag-sail, tether and natural re-entry times; more wear
shortens remaining life. Controlled burn re-entry barely changes (perigee is already dense).
Example (SAT-05): remaining life 207 / 107 / 72 min at 0.0 / 0.5 / 1.0.
The UI snaps to the three precomputed levels because it replays the RunLog.

## 5. Last Breath and retirement
**Q: What is the point of no return?**
A: Remaining life minus the time the cheapest affordable retirement needs, minus 5 minutes of
margin. It is 0 if no option is affordable.
**Q: The UI says RETIRE at t=63 but the satellite retires at t=78. Why?**
A: The verdict is an advisory early warning. The brain acts on its own rule (remaining life under
30 min). Retirement still finishes at t=103, well before an uncontrolled death.

## 6. Results and honesty
Seed 42 (180 min): ON 0.704 kg vs OFF 0.764 kg fuel; expected satellite loss 0.004 vs 0.063.
Seeds 1-10: ON used less fuel and lost no satellites on every seed. ON was worse on localisation
accuracy or false alarms on seeds 1, 7, 9 and 10 (sensing and brain, not physics). Report these.
**Do not claim** that the fuel saving independently validates the physics: it depends on a curve
calibrated to the mock.
