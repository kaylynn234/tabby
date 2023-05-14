function setup() {
  let navbar = document.getElementById('nav');

  navbar.addEventListener('click', () => navbar.classList.toggle('menu-active'));
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', setup);
} else {
  setup();
}
