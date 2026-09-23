CREATE TABLE faculty (
    code VARCHAR(20) PRIMARY KEY,
    name VARCHAR(200) NOT NULL
);

CREATE TABLE student_record (
    student_id VARCHAR(20) PRIMARY KEY,
    full_name VARCHAR(200) NOT NULL
);

CREATE TABLE enrolment (
    id BIGSERIAL PRIMARY KEY,
    student_id VARCHAR(20) NOT NULL UNIQUE REFERENCES student_record (student_id),
    faculty_code VARCHAR(20) NOT NULL REFERENCES faculty (code),
    group_name VARCHAR(50) NOT NULL,
    study_year INT NOT NULL,
    enrolment_status VARCHAR(20) NOT NULL,
    academic_standing VARCHAR(20) NOT NULL
);
