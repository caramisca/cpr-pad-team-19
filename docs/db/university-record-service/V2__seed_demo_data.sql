INSERT INTO faculty (code, name) VALUES
    ('FAF', 'Computers, Informatics and Microelectronics'),
    ('FCIM', 'Computer Science and Information Technologies'),
    ('FIMCP', 'Food Technology');

INSERT INTO student_record (student_id, full_name) VALUES
    ('1234567890', 'Diana Popescu'),
    ('2234567890', 'Andrei Munteanu'),
    ('3234567890', 'Elena Rusu');

INSERT INTO enrolment (student_id, faculty_code, group_name, study_year, enrolment_status, academic_standing) VALUES
    ('1234567890', 'FAF', 'FAF-231', 3, 'ENROLLED', 'GOOD'),
    ('2234567890', 'FCIM', 'FC-211', 1, 'ENROLLED', 'PROBATION'),
    ('3234567890', 'FAF', 'FAF-201', 4, 'GRADUATED', 'GOOD');
