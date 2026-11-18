-- Tabla de empresas (la app la crea sola; esto es por si la quieres crear a mano)
CREATE TABLE IF NOT EXISTS ESTAC_EMPRESAS (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    clave        VARCHAR(20)  NOT NULL UNIQUE,
    nombre       VARCHAR(80)  NOT NULL,
    host         VARCHAR(120) NOT NULL DEFAULT '',
    puerto       INT          NOT NULL DEFAULT 3306,
    usuario_db   VARCHAR(60)  NOT NULL DEFAULT '',
    clave_db     VARCHAR(120) NOT NULL DEFAULT '',
    base         VARCHAR(64)  NOT NULL DEFAULT '',
    usuario_app  VARCHAR(40)  NOT NULL DEFAULT '',
    clave_app    VARCHAR(60)  NOT NULL DEFAULT '',
    zona         VARCHAR(40)  NOT NULL DEFAULT 'America/Merida',
    activo       CHAR(1)      NOT NULL DEFAULT '1',
    creado       DATETIME     DEFAULT CURRENT_TIMESTAMP
) DEFAULT CHARSET=utf8mb4;

-- Ejemplo: otra base en el MISMO servidor de Railway (host vacío)
-- INSERT INTO ESTAC_EMPRESAS (clave,nombre,base,usuario_app,clave_app) VALUES ('EST02','Estac. Centro','estac_centro','centro','1234');
