
CREATE DATABASE IF NOT EXISTS barberbook
CHARACTER SET utf8mb4
COLLATE utf8mb4_unicode_ci;

USE barberbook;

-- 1. USUARIOS
CREATE TABLE IF NOT EXISTS usuarios (
    id_usuario INT AUTO_INCREMENT PRIMARY KEY,
    nombre VARCHAR(100) NOT NULL,
    apellido VARCHAR(100) NOT NULL,
    correo VARCHAR(150) NOT NULL UNIQUE,
    telefono VARCHAR(20),
    contrasena VARCHAR(255) NOT NULL,
    rol ENUM('cliente', 'barbero', 'administrador')
        NOT NULL DEFAULT 'cliente',
    fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. BARBEROS
CREATE TABLE IF NOT EXISTS barberos (
    id_barbero INT AUTO_INCREMENT PRIMARY KEY,
    id_usuario INT NOT NULL UNIQUE,
    especialidad VARCHAR(100),
    descripcion TEXT,
    activo BOOLEAN DEFAULT TRUE,
    FOREIGN KEY (id_usuario)
        REFERENCES usuarios(id_usuario)
);

-- 3. SERVICIOS
CREATE TABLE IF NOT EXISTS servicios (
    id_servicio INT AUTO_INCREMENT PRIMARY KEY,
    nombre VARCHAR(100) NOT NULL,
    descripcion TEXT,
    precio DECIMAL(10,2) NOT NULL,
    duracion_minutos INT NOT NULL,
    activo BOOLEAN DEFAULT TRUE,
    CHECK (precio >= 0),
    CHECK (duracion_minutos > 0)
);

-- 4. HORARIOS
CREATE TABLE IF NOT EXISTS horarios (
    id_horario INT AUTO_INCREMENT PRIMARY KEY,
    id_barbero INT NOT NULL,
    dia_semana TINYINT NOT NULL,
    hora_inicio TIME NOT NULL,
    hora_fin TIME NOT NULL,
    CHECK (dia_semana BETWEEN 1 AND 7),
    CHECK (hora_inicio < hora_fin),
    FOREIGN KEY (id_barbero)
        REFERENCES barberos(id_barbero)
);

-- 5. CITAS
CREATE TABLE IF NOT EXISTS citas (
    id_cita INT AUTO_INCREMENT PRIMARY KEY,
    id_cliente INT NOT NULL,
    id_barbero INT NOT NULL,
    id_servicio INT NOT NULL,
    fecha DATE NOT NULL,
    hora_inicio TIME NOT NULL,
    hora_fin TIME NOT NULL,
    estado ENUM(
        'pendiente',
        'confirmada',
        'rechazada',
        'cancelada',
        'completada'
    ) NOT NULL DEFAULT 'pendiente',
    observaciones TEXT,
    fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CHECK (hora_inicio < hora_fin),
    FOREIGN KEY (id_cliente)
        REFERENCES usuarios(id_usuario),
    FOREIGN KEY (id_barbero)
        REFERENCES barberos(id_barbero),
    FOREIGN KEY (id_servicio)
        REFERENCES servicios(id_servicio),
    INDEX idx_citas_agenda (id_barbero, fecha, estado)
);

-- 6. BLOQUEOS DE HORARIO
CREATE TABLE IF NOT EXISTS bloqueos_horario (
    id_bloqueo INT AUTO_INCREMENT PRIMARY KEY,
    id_barbero INT NOT NULL,
    fecha DATE NOT NULL,
    hora_inicio TIME NOT NULL,
    hora_fin TIME NOT NULL,
    motivo VARCHAR(255),
    CHECK (hora_inicio < hora_fin),
    FOREIGN KEY (id_barbero)
        REFERENCES barberos(id_barbero)
);

-- 7. NOTIFICACIONES
CREATE TABLE IF NOT EXISTS notificaciones (
    id_notificacion INT AUTO_INCREMENT PRIMARY KEY,
    id_usuario INT NOT NULL,
    id_cita INT,
    mensaje TEXT NOT NULL,
    leida BOOLEAN DEFAULT FALSE,
    fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (id_usuario)
        REFERENCES usuarios(id_usuario),
    FOREIGN KEY (id_cita)
        REFERENCES citas(id_cita)
        ON DELETE SET NULL
);
