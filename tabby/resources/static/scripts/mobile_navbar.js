function setup() {
  let navbar = document.getElementById('nav');

  navbar.addEventListener('click', () => {
    let action = navbar.classList.contains('menu-active') ? 'remove' : 'add';
    navbar.classList[action]('menu-active');
  });
}

if (document.readyState !== 'loading') {
  setup();
} else {
  document.addEventListener('DOMContentLoaded', setup);
}