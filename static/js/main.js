// ==================== SISTEMA DE PESTAÑAS ====================
function initTabs() {
    const tabButtons = document.querySelectorAll('.tab-button');
    const tabContents = document.querySelectorAll('.tab-content');

    tabButtons.forEach(button => {
        button.addEventListener('click', () => {
            const targetTab = button.dataset.tab;

            // Remover active de todos los botones y contenidos
            tabButtons.forEach(btn => btn.classList.remove('active'));
            tabContents.forEach(content => content.classList.remove('active'));

            // Agregar active al botón clickeado y su contenido
            button.classList.add('active');
            document.getElementById(targetTab).classList.add('active');
        });
    });
}

// ==================== CARGAR RESULTADOS DE DBPEDIA ====================
function loadDBpediaResults(term) {
    const container = document.getElementById('dbpedia-results-grid');
    const countElement = document.getElementById('dbpedia-count');
    
    if (!term || !term.trim()) {
        container.innerHTML = `
            <div class="no-results">
                🔍 Realiza una búsqueda para ver resultados de DBpedia
            </div>
        `;
        countElement.textContent = 'Esperando búsqueda...';
        return;
    }

    // Mostrar loading
    container.innerHTML = `
        <div class="loading-container active">
            <div class="spinner"></div>
            <div class="loading-text">
                Buscando en DBpedia<span class="loading-dots"><span>.</span><span>.</span><span>.</span></span>
            </div>
            <div class="loading-subtext">
                Esta parte puede tardar algunos segundos
            </div>
        </div>
    `;

    // Realizar búsqueda en DBpedia
    fetch("/dbpedia_search", {
        method: "POST",
        headers: { 
            "Content-Type": "application/json" 
        },
        body: JSON.stringify({ term: term })
    })
    .then(res => res.json())
    .then(data => {
        container.innerHTML = '';
        
        if (!data || data.length === 0) {
            container.innerHTML = `
                <div class="no-results">
                    🔍 No se encontraron resultados en DBpedia
                </div>
            `;
            countElement.textContent = '0 resultados';
            return;
        }

        // Actualizar contador
        countElement.textContent = `${data.length} resultado(s)`;

        // Crear tarjetas de resultados
        data.forEach(item => {
            const card = createDBpediaCard(item);
            container.appendChild(card);
        });
    })
    .catch(err => {
        console.error('Error consultando DBpedia:', err);
        container.innerHTML = `
            <div class="no-results">
                ❌ Error al cargar resultados de DBpedia
                <br><small style="font-size: 0.7em; color: #B8AFA5;">Por favor, intenta de nuevo</small>
            </div>
        `;
        countElement.textContent = 'Error';
    });
}

// ==================== CREAR TARJETA DE DBPEDIA ====================
function createDBpediaCard(item) {
    const card = document.createElement('div');
    card.className = 'card dbpedia-result';

    let html = `
        <div class="card-header">
            <h3>
                ${item.nombre || 'Sin nombre'}
                <span class="source-badge source-dbpedia">DBPEDIA</span>
            </h3>
        </div>
    `;

    // Thumbnail
    html += `
        <div class="thumbnail-container">
            ${item.thumbnail 
                ? `<img src="${item.thumbnail}" alt="${item.nombre || 'Imagen'}" 
                     onerror="this.parentElement.innerHTML='<div class=\\'no-thumbnail\\'>🖼️ Imagen no disponible</div>'">` 
                : `<div class="no-thumbnail">🖼️ Sin imagen disponible</div>`}
        </div>
    `;

    // Clases/Tipo
    if (item.clases && item.clases.length > 0) {
        html += `
            <div class="card-section">
                <div class="section-title">Tipo</div>
                <div class="tag-container">
                    ${item.clases.map(clase => `<span class="tag">${clase}</span>`).join('')}
                </div>
            </div>
        `;
    }

    // Ingredientes
    if (item.ingredientes && item.ingredientes.length > 0) {
        const maxIngredientes = 8;
        const ingredientes = item.ingredientes.slice(0, maxIngredientes);
        const remaining = item.ingredientes.length - maxIngredientes;

        html += `
            <div class="card-section">
                <div class="section-title">Ingredientes (DBpedia)</div>
                <ul>
                    ${ingredientes.map(ing => `<li>${ing}</li>`).join('')}
                    ${remaining > 0 ? `<li style="color: #999; font-style: italic;">...y ${remaining} más</li>` : ''}
                </ul>
            </div>
        `;
    }

    // Atributos
    if (item.atributos && Object.keys(item.atributos).length > 0) {
        html += `<div class="card-section">
            <div class="section-title">Información</div>
            <div class="attributes-grid">`;

        for (const [key, values] of Object.entries(item.atributos)) {
            if (key === 'dbpedia_uri') {
                html += `
                    <div class="attribute-item">
                        <div class="attribute-key">🔗 Ver en DBpedia</div>
                        <div class="attribute-values">
                            <a href="${values[0]}" target="_blank" class="dbpedia-link">${values[0]}</a>
                        </div>
                    </div>
                `;
            } else {
                html += `
                    <div class="attribute-item">
                        <div class="attribute-key">${key}</div>
                        <div class="attribute-values">${values.join(', ')}</div>
                    </div>
                `;
            }
        }

        html += `</div></div>`;
    }

    card.innerHTML = html;
    return card;
}

// ==================== VALIDACIÓN DE BÚSQUEDA ====================
function setupSearchValidation() {
    const form = document.getElementById('searchForm');
    const searchInput = document.getElementById('searchInput');

    form.addEventListener('submit', function(e) {
        const searchTerm = searchInput.value.trim();
        
        if (!searchTerm) {
            e.preventDefault();
            alert('Por favor, ingresa un término de búsqueda');
            return false;
        }

        // Scroll suave hacia arriba al buscar
        window.scrollTo({
            top: 0,
            behavior: 'smooth'
        });
    });
}

// ==================== INICIALIZACIÓN ====================
document.addEventListener('DOMContentLoaded', function() {
    // Inicializar sistema de pestañas
    initTabs();

    // Setup validación de búsqueda
    setupSearchValidation();

    // Obtener término de búsqueda del input
    const searchInput = document.getElementById('searchInput');
    const term = searchInput ? searchInput.value.trim() : '';

    // Si hay un término de búsqueda, cargar resultados de DBpedia
    if (term) {
        loadDBpediaResults(term);
    }
});
