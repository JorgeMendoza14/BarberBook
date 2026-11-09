-- ============================================================
-- DATOS DE PRUEBA - BarberBook
-- Ejecutar UNA sola vez, despues de schema.sql.
--
-- Todos los usuarios de prueba tienen la contraseña: Barber2026
--   Barberos: carlos@barberbook.com, miguel@barberbook.com
--   Clientes: ana@correo.com, luis@correo.com, maria@correo.com
-- (El administrador se crea con: python crear_admin.py)
-- ============================================================

SET NAMES utf8mb4;
USE barberbook;

SET @clave = 'scrypt:32768:8:1$qZGIA1Q1gBQ9C5ze$1348af5698222b1f12de47151dbf657ba2e299d8f1d6d6bc1e70370fd42fb460d38ccdf87ab130595eb0c04d86b11ac988739f11d69567dfd626d9cc0a2b4b79';

-- 1. USUARIOS
INSERT IGNORE INTO usuarios (nombre, apellido, correo, telefono, contrasena, rol) VALUES
('Carlos', 'Vera',     'carlos@barberbook.com', '0991111111', @clave, 'barbero'),
('Miguel', 'Torres',   'miguel@barberbook.com', '0992222222', @clave, 'barbero'),
('Ana',    'Cedeño',   'ana@correo.com',        '0993333333', @clave, 'cliente'),
('Luis',   'Zambrano', 'luis@correo.com',       '0994444444', @clave, 'cliente'),
('María',  'Loor',     'maria@correo.com',      '0995555555', @clave, 'cliente');

SET @u_carlos = (SELECT id_usuario FROM usuarios WHERE correo = 'carlos@barberbook.com');
SET @u_miguel = (SELECT id_usuario FROM usuarios WHERE correo = 'miguel@barberbook.com');
SET @ana      = (SELECT id_usuario FROM usuarios WHERE correo = 'ana@correo.com');
SET @luis     = (SELECT id_usuario FROM usuarios WHERE correo = 'luis@correo.com');
SET @maria    = (SELECT id_usuario FROM usuarios WHERE correo = 'maria@correo.com');

-- 2. BARBEROS
INSERT IGNORE INTO barberos (id_usuario, especialidad, descripcion) VALUES
(@u_carlos, 'Fade y degradados', 'Especialista en cortes modernos.'),
(@u_miguel, 'Barba y afeitado',  'Perfilado de barba con toalla caliente.');

SET @carlos = (SELECT id_barbero FROM barberos WHERE id_usuario = @u_carlos);
SET @miguel = (SELECT id_barbero FROM barberos WHERE id_usuario = @u_miguel);

-- 3. SERVICIOS
INSERT INTO servicios (nombre, descripcion, precio, duracion_minutos) VALUES
('Corte clásico',   'Corte con tijera y máquina.',         6.00, 30),
('Fade',            'Degradado a máquina con acabado.',    8.00, 40),
('Arreglo de barba','Perfilado y recorte de barba.',       4.00, 20),
('Corte + barba',   'Corte completo y arreglo de barba.', 10.00, 60);

SET @s_corte = (SELECT MAX(id_servicio) FROM servicios WHERE nombre = 'Corte clásico');
SET @s_fade  = (SELECT MAX(id_servicio) FROM servicios WHERE nombre = 'Fade');
SET @s_barba = (SELECT MAX(id_servicio) FROM servicios WHERE nombre = 'Arreglo de barba');
SET @s_combo = (SELECT MAX(id_servicio) FROM servicios WHERE nombre = 'Corte + barba');

-- 4. HORARIOS (1 = lunes ... 7 = domingo)
INSERT INTO horarios (id_barbero, dia_semana, hora_inicio, hora_fin) VALUES
(@carlos, 1, '09:00', '18:00'), (@carlos, 2, '09:00', '18:00'),
(@carlos, 3, '09:00', '18:00'), (@carlos, 4, '09:00', '18:00'),
(@carlos, 5, '09:00', '18:00'), (@carlos, 6, '09:00', '14:00'),
(@miguel, 2, '10:00', '19:00'), (@miguel, 3, '10:00', '19:00'),
(@miguel, 4, '10:00', '19:00'), (@miguel, 5, '10:00', '19:00'),
(@miguel, 6, '09:00', '15:00');

-- 5. CITAS
INSERT INTO citas (id_cliente, id_barbero, id_servicio, fecha, hora_inicio, hora_fin, estado, observaciones) VALUES
(@ana,   @carlos, @s_fade,  DATE_SUB(CURDATE(), INTERVAL 7 DAY), '10:00', '10:40', 'completada', 'Fade bajo'),
(@luis,  @miguel, @s_barba, DATE_SUB(CURDATE(), INTERVAL 3 DAY), '11:00', '11:20', 'completada', NULL),
(@maria, @carlos, @s_corte, DATE_SUB(CURDATE(), INTERVAL 2 DAY), '15:00', '15:30', 'rechazada',  NULL),
(@ana,   @miguel, @s_combo, DATE_ADD(CURDATE(), INTERVAL 2 DAY), '16:00', '17:00', 'confirmada', 'Barba en punta'),
(@luis,  @carlos, @s_corte, DATE_ADD(CURDATE(), INTERVAL 3 DAY), '09:30', '10:00', 'pendiente',  NULL),
(@maria, @carlos, @s_fade,  DATE_ADD(CURDATE(), INTERVAL 4 DAY), '11:00', '11:40', 'pendiente',  'Primera vez');

-- 6. BLOQUEOS DE HORARIO
INSERT INTO bloqueos_horario (id_barbero, fecha, hora_inicio, hora_fin, motivo) VALUES
(@carlos, DATE_ADD(CURDATE(), INTERVAL 3 DAY), '13:00', '14:00', 'Almuerzo'),
(@miguel, DATE_ADD(CURDATE(), INTERVAL 5 DAY), '10:00', '12:00', 'Cita médica');

-- 7. NOTIFICACIONES (se enlazan con las citas pendientes y confirmadas)
INSERT INTO notificaciones (id_usuario, id_cita, mensaje)
SELECT b.id_usuario, c.id_cita,
       CONCAT('Nueva cita reservada para el ', DATE_FORMAT(c.fecha, '%d/%m/%Y'),
              ' a las ', TIME_FORMAT(c.hora_inicio, '%H:%i'), '.')
FROM citas c
INNER JOIN barberos b ON b.id_barbero = c.id_barbero
WHERE c.estado IN ('pendiente', 'confirmada')
  AND c.id_barbero IN (@carlos, @miguel);
