"use strict";


/**
 * 全ページ共通JavaScript
 *
 * 主な処理:
 * ・PC表示でグローバルメニューを上部固定
 * ・スマホ用メニューバーを上部固定
 * ・ハンバーガーメニューの開閉
 * ・メニュー外クリックで閉じる
 * ・Escキーで閉じる
 * ・メニュー内リンククリックで閉じる
 * ・画面幅変更時の状態リセット
 * ・ページ上部へ戻るボタンの表示制御
 * ・ページ上部へのスムーズスクロール
 * ・機種詳細ページの閲覧履歴保存
 * ・お気に入り機種の追加と解除
 * ・閲覧履歴ページの一覧表示
 * ・お気に入りページの一覧表示
 */


/* ==================================================
   1. 共通設定
================================================== */

const MOBILE_BREAKPOINT = 768;

const MACHINE_HISTORY_STORAGE_KEY =
    "soubanavi_machine_history";

const MACHINE_FAVORITES_STORAGE_KEY =
    "soubanavi_machine_favorites";

const MACHINE_HISTORY_LIMIT = 30;


/* ==================================================
   2. 初期化
================================================== */

document.addEventListener(
    "DOMContentLoaded",
    function () {
        initializeStickyGlobalNavigation();
        initializeStickyMobileMenuBar();
        initializeHamburgerMenu();
        initializeScrollTopButton();

        initializeMachineHistory();
        initializeMachineFavorites();
        initializeHistoryPage();
        initializeFavoritesPage();
    }
);


/* ==================================================
   3. グローバルナビゲーション固定
================================================== */

/**
 * PC表示でグローバルナビゲーションを
 * スクロール時に画面上部へ固定する。
 *
 * スマホ表示では固定処理を無効にする。
 */
function initializeStickyGlobalNavigation() {
    const globalNavigation =
        document.getElementById(
            "global-navigation"
        );

    if (!globalNavigation) {
        return;
    }


    /*
     * ナビゲーション固定時の
     * レイアウト崩れを防ぐためのスペーサー。
     */
    const navigationPlaceholder =
        document.createElement("div");

    navigationPlaceholder.className =
        "global-nav-placeholder";

    navigationPlaceholder.setAttribute(
        "aria-hidden",
        "true"
    );

    globalNavigation.parentNode.insertBefore(
        navigationPlaceholder,
        globalNavigation
    );


    let navigationStartPosition = 0;
    let scrollTicking = false;


    /**
     * PC表示かどうかを返す。
     *
     * @returns {boolean}
     */
    function isDesktopView() {
        return (
            window.innerWidth
            > MOBILE_BREAKPOINT
        );
    }


    /**
     * ナビゲーションが固定されているかを返す。
     *
     * @returns {boolean}
     */
    function isNavigationFixed() {
        return globalNavigation.classList.contains(
            "is-fixed"
        );
    }


    /**
     * ナビゲーション固定開始位置を取得する。
     */
    function calculateNavigationPosition() {
        removeFixedNavigation();

        navigationStartPosition =
            globalNavigation
                .getBoundingClientRect()
                .top
            + window.scrollY;
    }


    /**
     * ナビゲーションを上部へ固定する。
     */
    function applyFixedNavigation() {
        if (isNavigationFixed()) {
            return;
        }

        navigationPlaceholder.style.height =
            `${globalNavigation.offsetHeight}px`;

        globalNavigation.classList.add(
            "is-fixed"
        );

        document.body.classList.add(
            "global-nav-fixed"
        );
    }


    /**
     * ナビゲーションの固定を解除する。
     */
    function removeFixedNavigation() {
        globalNavigation.classList.remove(
            "is-fixed"
        );

        document.body.classList.remove(
            "global-nav-fixed"
        );

        navigationPlaceholder.style.height =
            "0px";
    }


    /**
     * スクロール位置に応じて
     * ナビゲーションの固定状態を更新する。
     */
    function updateFixedNavigation() {
        if (!isDesktopView()) {
            removeFixedNavigation();

            return;
        }

        const currentScrollPosition =
            window.scrollY
            || document.documentElement.scrollTop;

        if (
            currentScrollPosition
            >= navigationStartPosition
        ) {
            applyFixedNavigation();
        } else {
            removeFixedNavigation();
        }
    }


    window.addEventListener(
        "scroll",
        function () {
            if (scrollTicking) {
                return;
            }

            scrollTicking = true;

            window.requestAnimationFrame(
                function () {
                    updateFixedNavigation();

                    scrollTicking = false;
                }
            );
        },
        {
            passive: true,
        }
    );


    window.addEventListener(
        "resize",
        debounce(
            function () {
                removeFixedNavigation();
                calculateNavigationPosition();
                updateFixedNavigation();
            },
            150
        )
    );


    window.addEventListener(
        "load",
        function () {
            calculateNavigationPosition();
            updateFixedNavigation();
        }
    );


    calculateNavigationPosition();
    updateFixedNavigation();
}


/* ==================================================
   4. スマホ用メニューバー固定
================================================== */

/**
 * スマホ表示でメニューバーを画面上部へ固定する。
 */
function initializeStickyMobileMenuBar() {
    const headerMenuArea =
        document.querySelector(
            ".header-menu-area"
        );

    if (!headerMenuArea) {
        return;
    }


    const placeholder =
        document.createElement("div");

    placeholder.className =
        "mobile-menu-placeholder";

    placeholder.setAttribute(
        "aria-hidden",
        "true"
    );

    headerMenuArea.parentNode.insertBefore(
        placeholder,
        headerMenuArea
    );


    let menuStartPosition = 0;
    let scrollTicking = false;


    function isMobileView() {
        return (
            window.innerWidth
            <= MOBILE_BREAKPOINT
        );
    }


    function removeFixedMenu() {
        headerMenuArea.classList.remove(
            "is-fixed"
        );

        placeholder.style.height =
            "0px";
    }


    function calculateMenuPosition() {
        removeFixedMenu();

        menuStartPosition =
            headerMenuArea
                .getBoundingClientRect()
                .top
            + window.scrollY;
    }


    function applyFixedMenu() {
        if (
            headerMenuArea.classList.contains(
                "is-fixed"
            )
        ) {
            return;
        }

        placeholder.style.height =
            `${headerMenuArea.offsetHeight}px`;

        headerMenuArea.classList.add(
            "is-fixed"
        );
    }


    function updateFixedMenu() {
        if (!isMobileView()) {
            removeFixedMenu();

            return;
        }

        const currentScrollPosition =
            window.scrollY
            || document.documentElement.scrollTop;

        if (
            currentScrollPosition
            >= menuStartPosition
        ) {
            applyFixedMenu();
        } else {
            removeFixedMenu();
        }
    }


    window.addEventListener(
        "scroll",
        function () {
            if (scrollTicking) {
                return;
            }

            scrollTicking = true;

            window.requestAnimationFrame(
                function () {
                    updateFixedMenu();

                    scrollTicking = false;
                }
            );
        },
        {
            passive: true,
        }
    );


    window.addEventListener(
        "resize",
        debounce(
            function () {
                removeFixedMenu();
                calculateMenuPosition();
                updateFixedMenu();
            },
            150
        )
    );


    window.addEventListener(
        "load",
        function () {
            calculateMenuPosition();
            updateFixedMenu();
        }
    );


    calculateMenuPosition();
    updateFixedMenu();
}


/* ==================================================
   5. ハンバーガーメニュー
================================================== */

/**
 * ハンバーガーメニューを初期化する。
 */
function initializeHamburgerMenu() {
    const menuToggle =
        document.querySelector(
            ".menu-toggle"
        );

    const globalNavigation =
        document.getElementById(
            "global-navigation"
        );

    if (!menuToggle || !globalNavigation) {
        return;
    }


    const navigationLinks =
        globalNavigation.querySelectorAll(
            "a"
        );


    function isMenuOpen() {
        return menuToggle.classList.contains(
            "is-open"
        );
    }


    function openMenu() {
        if (isMenuOpen()) {
            return;
        }

        menuToggle.classList.add(
            "is-open"
        );

        globalNavigation.classList.add(
            "is-open"
        );

        document.body.classList.add(
            "menu-open"
        );

        menuToggle.setAttribute(
            "aria-expanded",
            "true"
        );

        menuToggle.setAttribute(
            "aria-label",
            "メニューを閉じる"
        );
    }


    function closeMenu(
        restoreFocus = false
    ) {
        if (!isMenuOpen()) {
            return;
        }

        menuToggle.classList.remove(
            "is-open"
        );

        globalNavigation.classList.remove(
            "is-open"
        );

        document.body.classList.remove(
            "menu-open"
        );

        menuToggle.setAttribute(
            "aria-expanded",
            "false"
        );

        menuToggle.setAttribute(
            "aria-label",
            "メニューを開く"
        );

        if (restoreFocus) {
            menuToggle.focus();
        }
    }


    function toggleMenu() {
        if (isMenuOpen()) {
            closeMenu();
        } else {
            openMenu();
        }
    }


    menuToggle.addEventListener(
        "click",
        function () {
            toggleMenu();
        }
    );


    navigationLinks.forEach(
        function (navigationLink) {
            navigationLink.addEventListener(
                "click",
                function () {
                    closeMenu();
                }
            );
        }
    );


    document.addEventListener(
        "click",
        function (event) {
            if (!isMenuOpen()) {
                return;
            }

            const clickedElement =
                event.target;

            if (
                !(clickedElement instanceof Node)
            ) {
                return;
            }

            const clickedInsideMenu =
                globalNavigation.contains(
                    clickedElement
                );

            const clickedMenuButton =
                menuToggle.contains(
                    clickedElement
                );

            if (
                !clickedInsideMenu
                && !clickedMenuButton
            ) {
                closeMenu();
            }
        }
    );


    document.addEventListener(
        "keydown",
        function (event) {
            if (
                event.key !== "Escape"
                || !isMenuOpen()
            ) {
                return;
            }

            closeMenu(true);
        }
    );


    document.addEventListener(
        "keydown",
        function (event) {
            if (
                event.key !== "Tab"
                || !isMenuOpen()
                || window.innerWidth
                    > MOBILE_BREAKPOINT
            ) {
                return;
            }

            const focusableElements = [
                menuToggle,
                ...globalNavigation.querySelectorAll(
                    [
                        "a[href]",
                        "button:not([disabled])",
                        "input:not([disabled])",
                        "select:not([disabled])",
                        "textarea:not([disabled])",
                        '[tabindex]:not([tabindex="-1"])',
                    ].join(",")
                ),
            ].filter(
                function (element) {
                    return (
                        element
                            instanceof HTMLElement
                        && !element.hasAttribute(
                            "disabled"
                        )
                    );
                }
            );

            if (
                focusableElements.length
                === 0
            ) {
                return;
            }

            const firstFocusableElement =
                focusableElements[0];

            const lastFocusableElement =
                focusableElements[
                    focusableElements.length - 1
                ];

            if (
                event.shiftKey
                && document.activeElement
                    === firstFocusableElement
            ) {
                event.preventDefault();

                lastFocusableElement.focus();

                return;
            }

            if (
                !event.shiftKey
                && document.activeElement
                    === lastFocusableElement
            ) {
                event.preventDefault();

                firstFocusableElement.focus();
            }
        }
    );


    window.addEventListener(
        "resize",
        debounce(
            function () {
                if (
                    window.innerWidth
                    > MOBILE_BREAKPOINT
                ) {
                    closeMenu();
                }
            },
            150
        )
    );


    menuToggle.setAttribute(
        "aria-expanded",
        "false"
    );

    menuToggle.setAttribute(
        "aria-label",
        "メニューを開く"
    );
}


/* ==================================================
   6. スクロールトップ
================================================== */

/**
 * ページ上部へ戻るボタンを初期化する。
 */
function initializeScrollTopButton() {
    const scrollTopButton =
        document.getElementById(
            "scroll-top-button"
        );

    if (!scrollTopButton) {
        return;
    }


    const showPosition = 400;
    const hideTransitionDuration = 250;

    let hideTimer = null;


    function showScrollTopButton() {
        if (hideTimer !== null) {
            window.clearTimeout(
                hideTimer
            );

            hideTimer = null;
        }

        scrollTopButton.hidden = false;

        window.requestAnimationFrame(
            function () {
                scrollTopButton.classList.add(
                    "is-visible"
                );
            }
        );
    }


    function hideScrollTopButton() {
        scrollTopButton.classList.remove(
            "is-visible"
        );

        if (hideTimer !== null) {
            window.clearTimeout(
                hideTimer
            );
        }

        hideTimer = window.setTimeout(
            function () {
                if (
                    !scrollTopButton.classList.contains(
                        "is-visible"
                    )
                ) {
                    scrollTopButton.hidden = true;
                }

                hideTimer = null;
            },
            hideTransitionDuration
        );
    }


    function updateScrollTopButton() {
        const currentScrollPosition =
            window.scrollY
            || document.documentElement.scrollTop;

        if (
            currentScrollPosition
            >= showPosition
        ) {
            showScrollTopButton();
        } else {
            hideScrollTopButton();
        }
    }


    function scrollToPageTop() {
        const prefersReducedMotion =
            window.matchMedia(
                "(prefers-reduced-motion: reduce)"
            ).matches;

        window.scrollTo({
            top: 0,
            left: 0,
            behavior:
                prefersReducedMotion
                    ? "auto"
                    : "smooth",
        });
    }


    scrollTopButton.addEventListener(
        "click",
        function () {
            scrollToPageTop();
        }
    );


    let scrollTicking = false;

    window.addEventListener(
        "scroll",
        function () {
            if (scrollTicking) {
                return;
            }

            scrollTicking = true;

            window.requestAnimationFrame(
                function () {
                    updateScrollTopButton();

                    scrollTicking = false;
                }
            );
        },
        {
            passive: true,
        }
    );


    updateScrollTopButton();
}


/* ==================================================
   7. 機種情報取得
================================================== */

/**
 * machine_detail.htmlに出力された
 * current-machine-dataを取得する。
 *
 * @returns {Object|null}
 */
function getCurrentMachineData() {
    const dataElement =
        document.getElementById(
            "current-machine-data"
        );

    if (!dataElement) {
        return null;
    }

    try {
        const machine =
            JSON.parse(
                dataElement.textContent
            );

        return normalizeMachineData(
            machine
        );

    } catch (error) {
        console.warn(
            "機種情報を読み込めませんでした。",
            error
        );

        return null;
    }
}


/**
 * localStorageへ保存する機種情報を整形する。
 *
 * @param {Object} machine
 * @returns {Object|null}
 */
function normalizeMachineData(machine) {
    if (
        !machine
        || typeof machine !== "object"
    ) {
        return null;
    }

    const id =
        String(
            machine.id ?? ""
        ).trim();

    const name =
        String(
            machine.name ?? ""
        ).trim();

    if (!id || !name) {
        return null;
    }

    const rawPrice =
        machine.price;

    let price = null;

    if (
        rawPrice !== null
        && rawPrice !== undefined
        && rawPrice !== ""
        && Number.isFinite(
            Number(rawPrice)
        )
    ) {
        price = Number(
            rawPrice
        );
    }

    return {
        id: id,
        name: name,
        maker: String(
            machine.maker ?? ""
        ).trim(),
        image: String(
            machine.image ?? ""
        ).trim(),
        price: price,
        url: String(
            machine.url ?? ""
        ).trim(),
        savedAt: String(
            machine.savedAt
            || new Date().toISOString()
        ),
    };
}


/* ==================================================
   8. localStorage共通処理
================================================== */

/**
 * localStorageが使用できるか確認する。
 *
 * @returns {boolean}
 */
function isLocalStorageAvailable() {
    try {
        const testKey =
            "__soubanavi_storage_test__";

        window.localStorage.setItem(
            testKey,
            "1"
        );

        window.localStorage.removeItem(
            testKey
        );

        return true;

    } catch (error) {
        return false;
    }
}


/**
 * localStorageから機種一覧を取得する。
 *
 * @param {string} storageKey
 * @returns {Array<Object>}
 */
function getStoredMachines(
    storageKey
) {
    if (!isLocalStorageAvailable()) {
        return [];
    }

    try {
        const rawValue =
            window.localStorage.getItem(
                storageKey
            );

        if (!rawValue) {
            return [];
        }

        const parsedValue =
            JSON.parse(
                rawValue
            );

        if (!Array.isArray(parsedValue)) {
            return [];
        }

        return parsedValue
            .map(
                function (machine) {
                    return normalizeMachineData(
                        machine
                    );
                }
            )
            .filter(
                function (machine) {
                    return machine !== null;
                }
            );

    } catch (error) {
        console.warn(
            "保存データを読み込めませんでした。",
            error
        );

        return [];
    }
}


/**
 * localStorageへ機種一覧を保存する。
 *
 * @param {string} storageKey
 * @param {Array<Object>} machines
 * @returns {boolean}
 */
function saveStoredMachines(
    storageKey,
    machines
) {
    if (!isLocalStorageAvailable()) {
        return false;
    }

    try {
        window.localStorage.setItem(
            storageKey,
            JSON.stringify(
                machines
            )
        );

        return true;

    } catch (error) {
        console.warn(
            "保存データを書き込めませんでした。",
            error
        );

        return false;
    }
}


/**
 * 機種IDが一致する要素の位置を返す。
 *
 * @param {Array<Object>} machines
 * @param {string} machineId
 * @returns {number}
 */
function findMachineIndex(
    machines,
    machineId
) {
    return machines.findIndex(
        function (machine) {
            return (
                String(machine.id)
                === String(machineId)
            );
        }
    );
}


/* ==================================================
   9. 閲覧履歴
================================================== */

/**
 * 機種詳細ページを閲覧履歴へ保存する。
 */
function initializeMachineHistory() {
    const currentMachine =
        getCurrentMachineData();

    if (!currentMachine) {
        return;
    }

    addMachineToHistory(
        currentMachine
    );
}


/**
 * 閲覧履歴へ機種を追加する。
 *
 * 同じ機種がある場合は先頭へ移動する。
 *
 * @param {Object} machine
 */
function addMachineToHistory(machine) {
    const normalizedMachine =
        normalizeMachineData(
            machine
        );

    if (!normalizedMachine) {
        return;
    }

    const history =
        getStoredMachines(
            MACHINE_HISTORY_STORAGE_KEY
        );

    const filteredHistory =
        history.filter(
            function (historyMachine) {
                return (
                    historyMachine.id
                    !== normalizedMachine.id
                );
            }
        );

    const nextHistory = [
        {
            ...normalizedMachine,
            savedAt:
                new Date().toISOString(),
        },
        ...filteredHistory,
    ].slice(
        0,
        MACHINE_HISTORY_LIMIT
    );

    saveStoredMachines(
        MACHINE_HISTORY_STORAGE_KEY,
        nextHistory
    );
}


/**
 * 閲覧履歴ページを初期化する。
 */
function initializeHistoryPage() {
    const listElement =
        document.getElementById(
            "history-list"
        );

    if (!listElement) {
        return;
    }

    const emptyElement =
        document.getElementById(
            "history-empty"
        );

    const clearButton =
        document.getElementById(
            "clear-history-button"
        );


    function render() {
        const history =
            getStoredMachines(
                MACHINE_HISTORY_STORAGE_KEY
            );

        renderMachineList({
            machines: history,
            listElement: listElement,
            emptyElement: emptyElement,
            clearButton: clearButton,
            removeButtonLabel:
                "履歴から削除",
            onRemove:
                function (machineId) {
                    removeStoredMachine(
                        MACHINE_HISTORY_STORAGE_KEY,
                        machineId
                    );

                    render();
                },
        });
    }


    if (clearButton) {
        clearButton.addEventListener(
            "click",
            function () {
                const confirmed =
                    window.confirm(
                        "閲覧履歴をすべて削除しますか？"
                    );

                if (!confirmed) {
                    return;
                }

                saveStoredMachines(
                    MACHINE_HISTORY_STORAGE_KEY,
                    []
                );

                render();
            }
        );
    }


    render();
}


/* ==================================================
   10. お気に入り
================================================== */

/**
 * 機種詳細ページのお気に入りボタンを初期化する。
 */
function initializeMachineFavorites() {
    const currentMachine =
        getCurrentMachineData();

    const favoriteButton =
        document.getElementById(
            "favorite-toggle-button"
        );

    if (
        !currentMachine
        || !favoriteButton
    ) {
        return;
    }


    function updateButton() {
        const favorites =
            getStoredMachines(
                MACHINE_FAVORITES_STORAGE_KEY
            );

        const isFavorite =
            findMachineIndex(
                favorites,
                currentMachine.id
            ) !== -1;

        updateFavoriteButtonState(
            favoriteButton,
            isFavorite
        );
    }


    favoriteButton.addEventListener(
        "click",
        function () {
            toggleFavoriteMachine(
                currentMachine
            );

            updateButton();
        }
    );


    updateButton();
}


/**
 * お気に入りの追加・解除を切り替える。
 *
 * @param {Object} machine
 */
function toggleFavoriteMachine(machine) {
    const normalizedMachine =
        normalizeMachineData(
            machine
        );

    if (!normalizedMachine) {
        return;
    }

    const favorites =
        getStoredMachines(
            MACHINE_FAVORITES_STORAGE_KEY
        );

    const machineIndex =
        findMachineIndex(
            favorites,
            normalizedMachine.id
        );

    let nextFavorites = [];

    if (machineIndex === -1) {
        nextFavorites = [
            {
                ...normalizedMachine,
                savedAt:
                    new Date().toISOString(),
            },
            ...favorites,
        ];

    } else {
        nextFavorites =
            favorites.filter(
                function (favoriteMachine) {
                    return (
                        favoriteMachine.id
                        !== normalizedMachine.id
                    );
                }
            );
    }

    saveStoredMachines(
        MACHINE_FAVORITES_STORAGE_KEY,
        nextFavorites
    );
}


/**
 * お気に入りボタンの表示を更新する。
 *
 * @param {HTMLElement} button
 * @param {boolean} isFavorite
 */
function updateFavoriteButtonState(
    button,
    isFavorite
) {
    const icon =
        button.querySelector(
            ".favorite-toggle-icon"
        );

    const label =
        button.querySelector(
            ".favorite-toggle-label"
        );

    button.classList.toggle(
        "is-favorite",
        isFavorite
    );

    button.setAttribute(
        "aria-pressed",
        isFavorite
            ? "true"
            : "false"
    );

    if (icon) {
        icon.textContent =
            isFavorite
                ? "★"
                : "☆";
    }

    if (label) {
        label.textContent =
            isFavorite
                ? "お気に入りから削除"
                : "お気に入りに追加";
    }
}


/**
 * お気に入りページを初期化する。
 */
function initializeFavoritesPage() {
    const listElement =
        document.getElementById(
            "favorites-list"
        );

    if (!listElement) {
        return;
    }

    const emptyElement =
        document.getElementById(
            "favorites-empty"
        );

    const clearButton =
        document.getElementById(
            "clear-favorites-button"
        );


    function render() {
        const favorites =
            getStoredMachines(
                MACHINE_FAVORITES_STORAGE_KEY
            );

        renderMachineList({
            machines: favorites,
            listElement: listElement,
            emptyElement: emptyElement,
            clearButton: clearButton,
            removeButtonLabel:
                "お気に入りから削除",
            onRemove:
                function (machineId) {
                    removeStoredMachine(
                        MACHINE_FAVORITES_STORAGE_KEY,
                        machineId
                    );

                    render();
                },
        });
    }


    if (clearButton) {
        clearButton.addEventListener(
            "click",
            function () {
                const confirmed =
                    window.confirm(
                        "お気に入りをすべて削除しますか？"
                    );

                if (!confirmed) {
                    return;
                }

                saveStoredMachines(
                    MACHINE_FAVORITES_STORAGE_KEY,
                    []
                );

                render();
            }
        );
    }


    render();
}


/* ==================================================
   11. 履歴・お気に入り一覧表示
================================================== */

/**
 * 機種一覧をHTMLへ表示する。
 *
 * @param {Object} options
 */
function renderMachineList(options) {
    const {
        machines,
        listElement,
        emptyElement,
        clearButton,
        removeButtonLabel,
        onRemove,
    } = options;


    listElement.replaceChildren();

    listElement.setAttribute(
        "aria-busy",
        "false"
    );


    if (machines.length === 0) {
        listElement.hidden = true;

        if (emptyElement) {
            emptyElement.hidden = false;
        }

        if (clearButton) {
            clearButton.hidden = true;
        }

        return;
    }


    listElement.hidden = false;

    if (emptyElement) {
        emptyElement.hidden = true;
    }

    if (clearButton) {
        clearButton.hidden = false;
    }


    const fragment =
        document.createDocumentFragment();


    machines.forEach(
        function (machine) {
            const item =
                createMachineListItem({
                    machine: machine,
                    removeButtonLabel:
                        removeButtonLabel,
                    onRemove: onRemove,
                });

            fragment.appendChild(
                item
            );
        }
    );


    listElement.appendChild(
        fragment
    );
}


/**
 * 履歴・お気に入り一覧の
 * 1機種分のHTMLを作成する。
 *
 * @param {Object} options
 * @returns {HTMLElement}
 */
function createMachineListItem(options) {
    const {
        machine,
        removeButtonLabel,
        onRemove,
    } = options;


    const article =
        document.createElement(
            "article"
        );

    article.className =
        "user-machine-item";


    const detailLink =
        document.createElement(
            "a"
        );

    detailLink.className =
        "user-machine-item-link";

    detailLink.href =
        machine.url || "#";


    const imageArea =
        document.createElement(
            "div"
        );

    imageArea.className =
        "user-machine-image-area";


    if (machine.image) {
        const image =
            document.createElement(
                "img"
            );

        image.className =
            "user-machine-image";

        image.src =
            machine.image;

        image.alt =
            `${machine.name}の実機画像`;

        image.loading =
            "lazy";

        image.decoding =
            "async";

        imageArea.appendChild(
            image
        );

    } else {
        const placeholder =
            document.createElement(
                "div"
            );

        placeholder.className =
            "user-machine-image-placeholder";

        placeholder.textContent =
            "画像なし";

        imageArea.appendChild(
            placeholder
        );
    }


    const content =
        document.createElement(
            "div"
        );

    content.className =
        "user-machine-content";


    if (machine.maker) {
        const maker =
            document.createElement(
                "p"
            );

        maker.className =
            "user-machine-maker";

        maker.textContent =
            machine.maker;

        content.appendChild(
            maker
        );
    }


    const name =
        document.createElement(
            "h2"
        );

    name.className =
        "user-machine-name";

    name.textContent =
        machine.name;

    content.appendChild(
        name
    );


    if (
        machine.price !== null
        && Number.isFinite(
            Number(machine.price)
        )
    ) {
        const price =
            document.createElement(
                "p"
            );

        price.className =
            "user-machine-price";

        price.textContent =
            `最安価格 ${formatJapanesePrice(
                machine.price
            )}`;

        content.appendChild(
            price
        );
    }


    detailLink.appendChild(
        imageArea
    );

    detailLink.appendChild(
        content
    );


    const actionArea =
        document.createElement(
            "div"
        );

    actionArea.className =
        "user-machine-action";


    const removeButton =
        document.createElement(
            "button"
        );

    removeButton.className =
        "user-machine-remove-button";

    removeButton.type =
        "button";

    removeButton.textContent =
        removeButtonLabel;

    removeButton.addEventListener(
        "click",
        function () {
            onRemove(
                machine.id
            );
        }
    );


    actionArea.appendChild(
        removeButton
    );

    article.appendChild(
        detailLink
    );

    article.appendChild(
        actionArea
    );


    return article;
}


/**
 * 保存一覧から指定した機種を削除する。
 *
 * @param {string} storageKey
 * @param {string} machineId
 */
function removeStoredMachine(
    storageKey,
    machineId
) {
    const machines =
        getStoredMachines(
            storageKey
        );

    const nextMachines =
        machines.filter(
            function (machine) {
                return (
                    machine.id
                    !== String(machineId)
                );
            }
        );

    saveStoredMachines(
        storageKey,
        nextMachines
    );
}


/* ==================================================
   12. 共通補助関数
================================================== */

/**
 * 金額を日本円形式へ整形する。
 *
 * @param {number|string} value
 * @returns {string}
 */
function formatJapanesePrice(value) {
    const numericValue =
        Number(value);

    if (!Number.isFinite(numericValue)) {
        return "価格情報なし";
    }

    return (
        `${Math.round(
            numericValue
        ).toLocaleString("ja-JP")}円`
    );
}


/**
 * 関数の連続実行を抑制する。
 *
 * 主にresizeイベントで使用する。
 *
 * @param {Function} callback
 * @param {number} wait
 * @returns {Function}
 */
function debounce(
    callback,
    wait = 150
) {
    let timeoutId = null;

    return function (...args) {
        if (timeoutId !== null) {
            window.clearTimeout(
                timeoutId
            );
        }

        timeoutId = window.setTimeout(
            function () {
                callback.apply(
                    null,
                    args
                );
            },
            wait
        );
    };
}