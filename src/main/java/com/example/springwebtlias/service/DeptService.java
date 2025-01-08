package com.example.springwebtlias.service;

import com.example.springwebtlias.pojo.Dept;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
public interface DeptService {
    List<Dept> list();

    void delete(int id);

    void add(Dept dept);

    Dept selectById(Integer id);

    void change(Dept dept);
}
