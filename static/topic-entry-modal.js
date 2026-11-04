(() => {
  "use strict";

  function resize(modal) {
    if (!modal || modal.hidden) return;
    modal.querySelectorAll("textarea").forEach((field) => {
      if (!field.clientWidth) return;
      const borderHeight = field.offsetHeight - field.clientHeight;
      field.style.height = "0px";
      field.style.height = (field.scrollHeight + borderHeight) + "px";
    });
  }

  const modals = document.querySelectorAll(".topic-entry-modal");
  modals.forEach((modal) => {
    modal.addEventListener("input", (event) => {
      if (event.target.matches("textarea")) resize(modal);
    });
  });
  window.addEventListener("resize", () => modals.forEach(resize));
  window.topicEntryModal = { resize };
})();
