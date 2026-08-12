const API = "/api";

const state = {
    user: null,
    queues: [],
    history: [],
};


const registerScreen =
    document.getElementById("registerScreen");

const queueScreen =
    document.getElementById("queueScreen");

const registerForm =
    document.getElementById("registerForm");

const nicknameInput =
    document.getElementById("nicknameInput");

const registerError =
    document.getElementById("registerError");

const queuesContainer =
    document.getElementById("queuesContainer");

const emptyState =
    document.getElementById("emptyState");

const userBox =
    document.getElementById("userBox");

const currentNickname =
    document.getElementById("currentNickname");

const logoutButton =
    document.getElementById("logoutButton");

const connectionStatus =
    document.getElementById(
        "connectionStatus"
    );

const toast =
    document.getElementById("toast");


function escapeHtml(value) {
    const div =
        document.createElement("div");

    div.textContent =
        value ?? "";

    return div.innerHTML;
}


async function api(
    path,
    options = {}
) {
    const response = await fetch(
        `${API}${path}`,
        {
            credentials: "same-origin",
            ...options,

            headers: {
                "Content-Type":
                    "application/json",

                ...(options.headers || {}),
            },
        }
    );


    let data = {};

    try {
        data =
            await response.json();

    } catch {
        data = {};
    }


    if (!response.ok) {

        throw new Error(
            data.detail ||
            data.error ||
            "ошибка сервера"
        );
    }


    return data;
}


function showToast(message) {
    toast.textContent =
        message;

    toast.classList.remove(
        "hidden"
    );


    setTimeout(() => {

        toast.classList.add(
            "hidden"
        );

    }, 3000);
}


function showError(message) {
    registerError.textContent =
        message;

    registerError.classList.remove(
        "hidden"
    );
}


function hideError() {
    registerError.classList.add(
        "hidden"
    );
}


function showRegister() {
    registerScreen.classList.remove(
        "hidden"
    );

    queueScreen.classList.add(
        "hidden"
    );

    userBox.classList.add(
        "hidden"
    );
}


function showQueues() {
    registerScreen.classList.add(
        "hidden"
    );

    queueScreen.classList.remove(
        "hidden"
    );

    userBox.classList.remove(
        "hidden"
    );

    currentNickname.textContent =
        state.user.nickname;
}


function statusText(status) {

    switch (status) {

        case "active":
            return "сейчас";

        case "confirming":
            return "подтверждает";

        case "waiting":
            return "ждет";

        default:
            return status;
    }
}


function formatCountdown(seconds) {

    seconds = Math.max(
        0,
        Math.floor(seconds)
    );


    const hours =
        Math.floor(
            seconds / 3600
        );


    const minutes =
        Math.floor(
            (seconds % 3600) / 60
        );


    const secs =
        seconds % 60;


    return [
        hours
            .toString()
            .padStart(2, "0"),

        minutes
            .toString()
            .padStart(2, "0"),

        secs
            .toString()
            .padStart(2, "0"),

    ].join(":");
}


function formatTime(iso) {

    if (!iso) {
        return "неизвестно";
    }


    const date =
        new Date(iso);


    return date.toLocaleTimeString(
        "ru-RU",
        {
            hour: "2-digit",
            minute: "2-digit",
        }
    );
}


function formatDate(iso) {

    if (!iso) {
        return "";
    }


    const date =
        new Date(iso);


    return date.toLocaleDateString(
        "ru-RU",
        {
            day: "2-digit",
            month: "2-digit",
            year: "numeric",
        }
    );
}


function getMyQueue() {

    return state.queues.find(
        queue =>
            queue.my_entry
    );
}


function requestNotifications() {

    if (
        "Notification" in window &&
        Notification.permission ===
            "default"
    ) {

        Notification.requestPermission();
    }
}


function notify(
    title,
    body
) {

    if (
        !("Notification" in window)
    ) {
        return;
    }


    if (
        Notification.permission !==
        "granted"
    ) {
        return;
    }


    const key =
        `${title}:${body}`;


    const previous =
        sessionStorage.getItem(
            key
        );


    if (previous) {
        return;
    }


    sessionStorage.setItem(
        key,
        "1"
    );


    new Notification(
        title,
        {
            body,
            icon: "/favicon.ico",
        }
    );
}


function checkNotifications() {

    if (!state.user) {
        return;
    }


    for (
        const queue
        of state.queues
    ) {

        if (!queue.my_entry) {
            continue;
        }


        const entry =
            queue.my_entry;


        if (
            entry.status ===
            "confirming"
        ) {

            notify(
                "Твоя очередь",
                "Подтверди присутствие"
            );

            continue;
        }


        if (
            entry.status !==
            "waiting"
        ) {
            continue;
        }


        const wait =
            queue.estimated_wait_seconds;


        if (
            wait !== null &&
            wait !== undefined &&
            wait <= 10 * 60
        ) {

            notify(
                "Очередь скоро",
                `Твоя очередь примерно через ${
                    Math.max(
                        1,
                        Math.ceil(
                            wait / 60
                        )
                    )
                } мин.`
            );
        }
    }
}


function renderQueues() {

    queuesContainer.innerHTML =
        "";


    if (
        !state.queues.length
    ) {

        emptyState.classList.remove(
            "hidden"
        );

        return;
    }


    emptyState.classList.add(
        "hidden"
    );


    for (
        const queue
        of state.queues
    ) {

        const card =
            document.createElement(
                "div"
            );


        card.className =
            "queue-card";


        const entries =
            queue.entries || [];


        let entriesHtml =
            "";


        if (!entries.length) {

            entriesHtml = `
                <div class="queue-empty">
                    очередь пустая
                </div>
            `;

        } else {

            entriesHtml =
                entries
                    .map(
                        (
                            entry,
                            index
                        ) => {

                            const isMe =
                                Number(
                                    entry.user_id
                                ) ===
                                Number(
                                    state.user.user_id
                                );


                            let extra =
                                "";


                            if (
                                entry.status ===
                                "active"
                            ) {

                                const end =
                                    new Date(
                                        entry.end_at
                                    );


                                const seconds =
                                    Math.max(
                                        0,
                                        (
                                            end -
                                            new Date()
                                        ) / 1000
                                    );


                                extra = `
                                    <div
                                        class="
                                            entry-time
                                            active-time
                                        "
                                    >
                                        ${formatCountdown(
                                            seconds
                                        )}
                                    </div>
                                `;

                            } else if (
                                entry.status ===
                                "confirming"
                            ) {

                                const deadline =
                                    new Date(
                                        entry.confirm_deadline
                                    );


                                const seconds =
                                    Math.max(
                                        0,
                                        (
                                            deadline -
                                            new Date()
                                        ) / 1000
                                    );


                                extra = `
                                    <div
                                        class="
                                            entry-time
                                            confirming-time
                                        "
                                    >
                                        ${formatCountdown(
                                            seconds
                                        )}
                                    </div>
                                `;
                            }


                            return `
                                <div class="entry">

                                    <div class="position">
                                        ${index + 1}
                                    </div>

                                    <div
                                        class="
                                            entry-name
                                            ${
                                                isMe
                                                    ? "me"
                                                    : ""
                                            }
                                        "
                                    >
                                        ${escapeHtml(
                                            entry.display_name
                                        )}
                                    </div>

                                    <div class="entry-right">

                                        <div
                                            class="
                                                entry-status
                                                ${escapeHtml(
                                                    entry.status
                                                )}
                                            "
                                        >
                                            ${statusText(
                                                entry.status
                                            )}
                                        </div>

                                        ${extra}

                                    </div>

                                </div>
                            `;
                        }
                    )
                    .join("");
        }


        let personalInfo =
            "";


        if (
            queue.my_entry
        ) {

            if (
                queue.my_entry.status ===
                "waiting"
            ) {

                personalInfo = `
                    <div class="personal-info">

                        <div>
                            <span>
                                твоя позиция
                            </span>

                            <strong>
                                #${
                                    queue.position
                                    ?? "?"
                                }
                            </strong>
                        </div>

                        <div>
                            <span>
                                перед тобой
                            </span>

                            <strong>
                                ${
                                    queue.ahead
                                    ?? 0
                                }
                        </div>

                        <div>
                            <span>
                                примерно ждать
                            </span>

                            <strong>
                                ${
                                    queue
                                        .estimated_wait_text
                                    ?? "..."
                                }
                            </strong>
                        </div>

                        <div>
                            <span>
                                начало
                            </span>

                            <strong>
                                ${
                                    formatTime(
                                        queue
                                            .estimated_start
                                    )
                                }
                            </strong>
                        </div>

                    </div>
                `;
            }


            if (
                queue.my_entry.status ===
                "active"
            ) {

                const end =
                    new Date(
                        queue.my_entry.end_at
                    );


                const seconds =
                    Math.max(
                        0,
                        (
                            end -
                            new Date()
                        ) / 1000
                    );


                personalInfo = `
                    <div class="active-panel">

                        <div>
                            твоя очередь
                        </div>

                        <strong>
                            ${formatCountdown(
                                seconds
                            )}
                        </strong>

                        <span>
                            осталось
                        </span>

                    </div>
                `;
            }


            if (
                queue.my_entry.status ===
                "confirming"
            ) {

                const deadline =
                    new Date(
                        queue
                            .my_entry
                            .confirm_deadline
                    );


                const seconds =
                    Math.max(
                        0,
                        (
                            deadline -
                            new Date()
                        ) / 1000
                    );


                personalInfo = `
                    <div class="confirm-panel">

                        <div>
                            твоя очередь подошла
                        </div>

                        <strong>
                            ${formatCountdown(
                                seconds
                            )}
                        </strong>

                        <span>
                            на подтверждение
                        </span>

                    </div>
                `;
            }
        }


        let actions =
            "";


        if (
            queue.my_entry
        ) {

            if (
                queue.my_entry.status ===
                "confirming"
            ) {

                actions += `
                    <button
                        class="
                            action-button
                            confirm
                        "
                        onclick="
                            confirmQueue(
                                ${queue.chat_id}
                            )
                        "
                    >
                        я здесь
                    </button>
                `;
            }


            actions += `
                <button
                    class="
                        action-button
                        danger
                    "
                    onclick="
                        leaveQueue(
                            ${queue.chat_id}
                        )
                    "
                >
                    выйти
                </button>
            `;

        } else {

            actions = `
                <button
                    class="action-button"
                    onclick="
                        joinQueue(
                            ${queue.chat_id}
                        )
                    "
                >
                    встать в очередь
                </button>
            `;
        }


        card.innerHTML = `
            <div class="queue-header">

                <div>
                    <div class="queue-title">
                        ${escapeHtml(
                            queue.name
                        )}
                    </div>

                    <div class="queue-id">
                        ${queue.chat_id}
                    </div>
                </div>

                <div class="queue-average">
                    среднее:
                    ${
                        queue
                            .average_duration_text
                    }
                </div>

            </div>

            <div class="queue-body">

                ${personalInfo}

                ${entriesHtml}

                <div class="queue-actions">
                    ${actions}
                </div>

            </div>
        `;


        queuesContainer.appendChild(
            card
        );
    }
}


function renderHistory() {

    const container =
        document.getElementById(
            "historyContainer"
        );


    if (!container) {
        return;
    }


    if (
        !state.history.length
    ) {

        container.innerHTML = `
            <div class="history-empty">
                истории пока нет
            </div>
        `;

        return;
    }


    container.innerHTML =
        state.history
            .map(
                item => {

                    const status =
                        item.status ===
                        "completed"
                            ? "завершено"
                            : item.status ===
                              "expired"
                                ? "истекло"
                                : "отменено";


                    return `
                        <div class="history-item">

                            <div>
                                <strong>
                                    очередь ${
                                        item.chat_id
                                    }
                                </strong>

                                <span>
                                    ${
                                        formatDate(
                                            item.started_at ||
                                            item.joined_at
                                        )
                                    }
                                </span>
                            </div>

                            <div>
                                ${
                                    formatTime(
                                        item.started_at
                                    )
                                }

                                ${
                                    item.duration_text
                                        ? ` · ${
                                            item.duration_text
                                          }`
                                        : ""
                                }
                            </div>

                            <div class="history-status">
                                ${status}
                            </div>

                        </div>
                    `;
                }
            )
            .join("");
}


async function loadQueues() {

    try {

        const data =
            await api(
                "/queues"
            );


        state.queues =
            data.queues || [];


        renderQueues();

        checkNotifications();


        connectionStatus
            .classList
            .remove(
                "offline"
            );


        connectionStatus.innerHTML = `
            <span></span>
            подключено
        `;

    } catch {

        connectionStatus
            .classList
            .add(
                "offline"
            );


        connectionStatus.innerHTML = `
            <span></span>
            нет соединения
        `;
    }
}


async function loadHistory() {

    try {

        const data =
            await api(
                "/history"
            );


        state.history =
            data.history || [];


        renderHistory();

    } catch {
        // история необязательна
    }
}


async function register(
    nickname
) {

    hideError();


    try {

        const data =
            await api(
                "/register",
                {
                    method: "POST",

                    body: JSON.stringify({
                        nickname,
                    }),
                }
            );


        state.user =
            data.user;


        showQueues();

        await loadQueues();

        await loadHistory();


        requestNotifications();


        showToast(
            `ты вошел как ${nickname}`
        );

    } catch (error) {

        showError(
            error.message
        );
    }
}


async function joinQueue(
    chatId
) {

    try {

        await api(
            `/queues/${chatId}/join`,
            {
                method: "POST",
            }
        );


        await loadQueues();


        showToast(
            "ты встал в очередь"
        );

    } catch (error) {

        showToast(
            error.message
        );
    }
}


async function leaveQueue(
    chatId
) {

    const ok =
        confirm(
            "Выйти из очереди?"
        );


    if (!ok) {
        return;
    }


    try {

        await api(
            `/queues/${chatId}/leave`,
            {
                method: "POST",
            }
        );


        await loadQueues();


        showToast(
            "ты вышел из очереди"
        );

    } catch (error) {

        showToast(
            error.message
        );
    }
}


async function confirmQueue(
    chatId
) {

    try {

        await api(
            `/queues/${chatId}/confirm`,
            {
                method: "POST",
            }
        );


        await loadQueues();


        showToast(
            "очередь подтверждена"
        );

    } catch (error) {

        showToast(
            error.message
        );
    }
}


async function logout() {

    try {

        await api(
            "/logout",
            {
                method: "POST",
            }
        );

    } catch {
        // ничего
    }


    state.user = null;
    state.queues = [];
    state.history = [];


    showRegister();


    nicknameInput.value =
        "";
}


registerForm.addEventListener(
    "submit",
    async event => {

        event.preventDefault();


        const nickname =
            nicknameInput
                .value
                .trim();


        if (
            nickname.length < 2
        ) {

            showError(
                "ник слишком короткий"
            );

            return;
        }


        if (
            nickname.length > 32
        ) {

            showError(
                "ник слишком длинный"
            );

            return;
        }


        await register(
            nickname
        );
    }
);


logoutButton.addEventListener(
    "click",
    logout
);


// Обновляем состояние.
// 5 секунд достаточно, чтобы человек не ждал,
// но сервер при этом не получает пулемёт из GET.
setInterval(
    () => {

        if (state.user) {
            loadQueues();
        }

    },
    5000
);


// Локальный таймер перерисовывает секунды,
// не обращаясь к серверу.
setInterval(
    () => {

        if (state.user) {
            renderQueues();
        }

    },
    1000
);


loadUser();


async function loadUser() {

    try {

        const data =
            await api(
                "/me"
            );


        state.user =
            data.user;


        showQueues();


        await loadQueues();

        await loadHistory();


        requestNotifications();

    } catch {

        state.user =
            null;


        showRegister();
    }
}