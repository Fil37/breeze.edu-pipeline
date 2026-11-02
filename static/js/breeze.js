// breeze studio: the only script. Dashboard: a card's video plays (muted) while the mouse is on it.
// Channel page: a scene of the plan jumps the player to it; the scene being played is lit.
document.querySelectorAll(".thumb video").forEach(video => {
  const card = video.closest(".card");
  card.addEventListener("mouseenter", () => { video.play().catch(() => {}); });
  card.addEventListener("mouseleave", () => { video.pause(); });
});
const player = document.getElementById("player");
if (player) {
  const buttons = [...document.querySelectorAll(".seek")];
  buttons.forEach(button => button.addEventListener("click", () => {
    player.currentTime = Number(button.dataset.t) || 0;
    player.play().catch(() => {});
  }));
  player.addEventListener("timeupdate", () => {
    let current = null;
    for (const button of buttons) if (Number(button.dataset.t) <= player.currentTime + 0.05) current = button;
    buttons.forEach(button => button.classList.toggle("now", button === current));
  });
}
