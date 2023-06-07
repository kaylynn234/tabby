const CAN_EDIT = ['show-delete', 'show-edit'];
const CAN_DELETE = ['show-edit', 'show-delete'];

function setupAutoroleActions() {
  let forms = document.querySelectorAll('.grid.autoroles > form.row');

  forms.forEach(form => {
    let actions = form.querySelector('.actions');

    form.elements['granted_at'].addEventListener('input', event => {
      let { value: rawValue, placeholder: rawPlaceholder } = event.target;
      let [value, placeholder] = [rawValue, rawPlaceholder].map(Number);
      let hasText = /\S/.test(rawValue) && /\S/.test(rawPlaceholder)

      let isValid;

      // Empty strings are converted to zeroes, so we check that text is present just to be safe.
      if (value === placeholder && hasText) {
        event.target.value = "";
        isValid = false;
      } else {
        isValid = event.target.checkValidity();
      }

      let [oldClass, newClass] = isValid ? CAN_EDIT : CAN_DELETE;

      actions.classList.remove(oldClass);
      actions.classList.add(newClass);
    });

    actions.classList.add('show-delete');
  });
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', setupAutoroleActions);
} else {
  setupAutoroleActions();
}
