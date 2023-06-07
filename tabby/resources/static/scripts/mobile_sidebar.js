const ICON_OPEN_SIDEBAR = 'bi-list';
const ICON_CLOSE_SIDEBAR = 'bi-x-lg';

// These represent transitions from `a -> b` and are used to switch icon classes when states change.
const TO_CLOSE_ICON = [ICON_OPEN_SIDEBAR, ICON_CLOSE_SIDEBAR];
const TO_OPEN_ICON = [ICON_CLOSE_SIDEBAR, ICON_OPEN_SIDEBAR];

function setupMobileSidebar() {
  let menuToggle = document.getElementById('sidebar-menu-toggle');
  let menuToggleIcon = menuToggle.querySelector('.bi');
  let sidebar = document.getElementById('sidebar');

  menuToggle.addEventListener('click', () => {
    let isDisplayed = sidebar.classList.toggle('displayed');
    let [oldClass, newClass] = isDisplayed ? TO_CLOSE_ICON : TO_OPEN_ICON;

    menuToggleIcon.classList.remove(oldClass);
    menuToggleIcon.classList.add(newClass);
  });
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', setupMobileSidebar);
} else {
  setupMobileSidebar();
}
