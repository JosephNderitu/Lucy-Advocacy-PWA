// Ngima Wangai & Company Advocates — global site JS
document.addEventListener('DOMContentLoaded', function () {

  // ---- Mobile menu toggle ----
  var menuBtn = document.getElementById('mobile-menu-btn');
  var menu = document.getElementById('mobile-menu');
  var menuIcon = document.getElementById('mobile-menu-icon');

  function closeMenu() {
    menu.classList.add('hidden');
    menuBtn.setAttribute('aria-expanded', 'false');
    menuIcon.classList.remove('fa-xmark');
    menuIcon.classList.add('fa-bars');
  }

  function openMenu() {
    menu.classList.remove('hidden');
    menuBtn.setAttribute('aria-expanded', 'true');
    menuIcon.classList.remove('fa-bars');
    menuIcon.classList.add('fa-xmark');
  }

  if (menuBtn && menu) {
    menuBtn.addEventListener('click', function () {
      var isOpen = menuBtn.getAttribute('aria-expanded') === 'true';
      isOpen ? closeMenu() : openMenu();
    });

    // Close the mobile menu after tapping a link
    menu.querySelectorAll('a').forEach(function (link) {
      link.addEventListener('click', closeMenu);
    });

    // Close the mobile menu if the viewport grows back to desktop width
    window.addEventListener('resize', function () {
      if (window.innerWidth >= 1024) {
        closeMenu();
      }
    });
  }

  // ---- Sticky header shadow on scroll ----
  var header = document.getElementById('site-header');
  function updateHeaderShadow() {
    if (window.scrollY > 8) {
      header.classList.add('is-scrolled');
    } else {
      header.classList.remove('is-scrolled');
    }
  }
  if (header) {
    updateHeaderShadow();
    window.addEventListener('scroll', updateHeaderShadow, { passive: true });
  }
});