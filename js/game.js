// js/game.js 
const CARD_VALUES = ['A', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K'];
const CARD_SUITS = { 'hearts': 'H', 'diamonds': 'D', 'clubs': 'C', 'spades': 'S' };

function newGame() {
  const deck = CARD_VALUES.flatMap(value => 
    Object.entries(CARD_SUITS).map(([suitName, suitCode]) => ({
      value, suitCode, fileName: `${value}${suitCode}.png`
    }))
  ).sort(() => Math.random() - 0.5);

  deck.slice(0, 4).forEach((card, i) => {
    document.getElementById(`card${i+1}`).src = `assets/pictures/classic/${card.fileName}`;
  });
}

window.onload = () => {
  document.getElementById('new-game-btn').addEventListener('click', newGame);
  newGame();
};

console.log("Testing image paths:");
['AC','AD','AH','AS'].forEach(code => {
  const img = new Image();
  img.src = `assets/pictures/${code}.png`;
  img.onload = () => console.log(`${code}.png loads OK`);
  img.onerror = () => console.error(`${code}.png FAILED`);
});
