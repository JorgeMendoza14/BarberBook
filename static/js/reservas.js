// Formulario de reserva: cuando el cliente elige barbero, servicio y
// fecha, se piden al servidor las horas libres y se muestran como botones.
document.addEventListener("DOMContentLoaded", function () {
    const formulario = document.querySelector("form[data-reserva]");
    if (!formulario) {
        return;
    }

    const barbero = formulario.querySelector("[name=id_barbero]");
    const servicio = formulario.querySelector("[name=id_servicio]");
    const fecha = formulario.querySelector("[name=fecha]");
    const hora = formulario.querySelector("[name=hora]");
    const cajaHoras = document.getElementById("horas-disponibles");
    const cajaHorario = document.getElementById("horario-barbero");

    function mostrarMensaje(texto) {
        cajaHoras.innerHTML = "";
        const parrafo = document.createElement("p");
        parrafo.className = "horas-mensaje";
        parrafo.textContent = texto;
        cajaHoras.appendChild(parrafo);
    }

    function mostrarHorario(horario) {
        cajaHorario.innerHTML = "";
        if (horario.length === 0) {
            return;
        }
        const titulo = document.createElement("span");
        titulo.textContent = "Horario del barbero: ";
        cajaHorario.appendChild(titulo);
        horario.forEach(function (turno) {
            const etiqueta = document.createElement("span");
            etiqueta.className = "horario-chip";
            etiqueta.textContent = turno.dia + " " + turno.inicio + "–" + turno.fin;
            cajaHorario.appendChild(etiqueta);
        });
    }

    function mostrarHoras(horas) {
        cajaHoras.innerHTML = "";
        // Si la hora que estaba elegida ya no esta libre, se borra
        if (!horas.includes(hora.value)) {
            hora.value = "";
        }
        horas.forEach(function (texto) {
            const boton = document.createElement("button");
            boton.type = "button";
            boton.className = "hora-opcion";
            boton.textContent = texto;
            if (texto === hora.value) {
                boton.classList.add("activa");
            }
            boton.addEventListener("click", function () {
                cajaHoras.querySelectorAll(".hora-opcion").forEach(function (b) {
                    b.classList.remove("activa");
                });
                boton.classList.add("activa");
                hora.value = texto;
            });
            cajaHoras.appendChild(boton);
        });
    }

    async function cargarHoras() {
        if (!barbero.value || !servicio.value || !fecha.value) {
            mostrarMensaje("Elige barbero, servicio y fecha para ver las horas libres.");
            cajaHorario.innerHTML = "";
            return;
        }

        mostrarMensaje("Buscando horas libres…");
        const parametros = new URLSearchParams({
            id_barbero: barbero.value,
            id_servicio: servicio.value,
            fecha: fecha.value,
            id_cita: cajaHoras.dataset.idCita || ""
        });

        try {
            const respuesta = await fetch(cajaHoras.dataset.url + "?" + parametros);
            const datos = await respuesta.json();
            mostrarHorario(datos.horario);
            if (datos.horas.length === 0) {
                hora.value = "";
                mostrarMensaje(datos.mensaje);
            } else {
                mostrarHoras(datos.horas);
            }
        } catch (error) {
            mostrarMensaje("No se pudo consultar la disponibilidad.");
        }
    }

    barbero.addEventListener("change", cargarHoras);
    servicio.addEventListener("change", cargarHoras);
    fecha.addEventListener("change", cargarHoras);

    formulario.addEventListener("submit", function (evento) {
        if (!hora.value) {
            evento.preventDefault();
            alert("Elige una de las horas disponibles.");
        }
    });

    cargarHoras();
});
